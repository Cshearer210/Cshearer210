"""Excel export: the agent-facing call sheet.

Four sheets, and the second one is the one that matters.

  Call List  - leads that cleared every check, ranked by probability of closing.
  Held       - leads that did not clear, each with the specific reason. Nothing is
               dropped silently, because most holds are fixable work items rather
               than dead leads. "Needs a DNC scrub" and "is on the federal DNC
               registry" are both holds and only one of them is a loss.
  Hold Summary - holds grouped by reason, so the fixable bulk is visible at a glance.
  Provenance - where the scoring numbers came from, and what they are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .compliance import GateResult, resolve_timezone
from .schema import Check, Lead
from .scoring import ScoreBasis, ScoreResult

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
BLOCK_FILL = PatternFill("solid", fgColor="F8CBAD")   # hard stop
UNKNOWN_FILL = PatternFill("solid", fgColor="FFE699")  # fixable
NOTE_FONT = Font(italic=True, color="595959")


@dataclass
class ScoredLead:
    lead: Lead
    gate: GateResult
    score: Optional[ScoreResult] = None


CALL_COLUMNS = [
    ("Rank", 6), ("Score", 8), ("Name", 22), ("Age", 6), ("Phone", 14),
    ("Email", 26), ("Address", 26), ("City", 16), ("State", 7), ("ZIP", 8),
    ("Call Window (local)", 19), ("Why This Lead", 52), ("Est. Value", 11),
    ("Close Prob.", 11), ("Source", 16), ("Lead Type", 15), ("Lead Age (d)", 12),
    ("Consent Cert", 30), ("Consent Date", 20), ("DNC Status", 14),
    ("DNC Checked", 20), ("State Flags", 26),
]

HELD_COLUMNS = [
    ("Name", 22), ("Phone", 14), ("State", 7), ("Hold Type", 11),
    ("Reason", 62), ("Fixable", 9), ("Source", 16), ("Lead Type", 15),
]


def _style_header(ws, columns) -> None:
    for i, (title, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=i, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"


def _local_window(lead: Lead, now: datetime) -> str:
    tz = resolve_timezone(lead)
    if tz is None:
        return "unknown timezone"
    return now.astimezone(tz).strftime("%H:%M %Z")


def build_workbook(
    scored: Sequence[ScoredLead],
    now: Optional[datetime] = None,
    commission_per_sale_cents: int = 70_000,
) -> Workbook:
    now = now or datetime.now(timezone.utc)
    wb = Workbook()

    # --- Call List -----------------------------------------------------------
    ws = wb.active
    ws.title = "Call List"
    _style_header(ws, CALL_COLUMNS)

    callable_leads = [s for s in scored if s.gate.callable_now and s.score is not None]
    callable_leads.sort(key=lambda s: s.score.score, reverse=True)

    for rank, item in enumerate(callable_leads, start=1):
        lead, sc = item.lead, item.score
        age_days = lead.age_days(now)
        ws.append([
            rank,
            sc.score,
            lead.full_name(),
            lead.self_reported.age,
            lead.phone,
            lead.email,
            lead.address1,
            lead.city,
            lead.state,
            lead.postal_code,
            _local_window(lead, now),
            sc.rationale,
            round(sc.expected_value_cents / 100.0, 2),
            f"{sc.p_close:.1%}",
            lead.vendor,
            lead.lead_type.value,
            round(age_days, 1) if age_days is not None else None,
            lead.consent.trustedform_url or lead.consent.jornaya_leadid,
            lead.consent.consent_timestamp.strftime("%Y-%m-%d %H:%M") if lead.consent.consent_timestamp else None,
            lead.dnc_status.value,
            lead.dnc_checked_at.strftime("%Y-%m-%d %H:%M") if lead.dnc_checked_at else None,
            "; ".join(item.gate.warnings) or None,
        ])

    # --- Held ---------------------------------------------------------------
    ws2 = wb.create_sheet("Held")
    _style_header(ws2, HELD_COLUMNS)
    held = [s for s in scored if not s.gate.callable_now]
    # Blocks first: they need a different decision than the fixable ones.
    held.sort(key=lambda s: (not s.gate.blocking, s.lead.state or ""))

    for item in held:
        lead, g = item.lead, item.gate
        hard = bool(g.blocking)
        failing = g.blocking if hard else g.unknown
        row = [
            lead.full_name(),
            lead.phone,
            lead.state,
            "BLOCK" if hard else "UNKNOWN",
            "; ".join(f"{c.name}: {c.reason}" for c in failing),
            "no" if hard else "yes",
            lead.vendor,
            lead.lead_type.value,
        ]
        ws2.append(row)
        fill = BLOCK_FILL if hard else UNKNOWN_FILL
        for col in range(1, len(HELD_COLUMNS) + 1):
            ws2.cell(row=ws2.max_row, column=col).fill = fill

    # --- Hold Summary --------------------------------------------------------
    ws3 = wb.create_sheet("Hold Summary")
    _style_header(ws3, [("Check", 24), ("Status", 11), ("Count", 8), ("Fixable", 9), ("What Clears It", 56)])
    remedy = {
        ("dnc", Check.UNKNOWN): "Run a DNC scrub; re-scrub anything older than 31 days.",
        ("dnc", Check.BLOCK): "Not callable. Direct mail only, or drop.",
        ("consent", Check.UNKNOWN): "Get the certificate URL and consent language from the vendor.",
        ("consent", Check.BLOCK): "Certificate was never claimed and has aged out. Not callable.",
        ("internal_suppression", Check.UNKNOWN): "Point the gate at your suppression store.",
        ("internal_suppression", Check.BLOCK): "Prior opt-out. Permanently suppressed.",
        ("litigator", Check.UNKNOWN): "Run the list through a litigator scrub.",
        ("litigator", Check.BLOCK): "Known TCPA plaintiff. Do not call.",
        ("calling_window", Check.UNKNOWN): "Add ZIP codes, or wire a ZIP-to-timezone dataset.",
        ("calling_window", Check.BLOCK): "Legal, just not right now. Re-queue for the local window.",
        ("state_frequency_cap", Check.UNKNOWN): "Connect call history so the FL/OK 3-per-24h cap can be counted.",
        ("state_frequency_cap", Check.BLOCK): "Daily cap reached. Re-queue for tomorrow.",
    }
    tally: Counter = Counter()
    for item in held:
        for c in item.gate.checks:
            if c.status in (Check.BLOCK, Check.UNKNOWN):
                tally[(c.name, c.status)] += 1
    for (name, status), count in tally.most_common():
        ws3.append([
            name, status.value, count,
            "yes" if status is Check.UNKNOWN else "no",
            remedy.get((name, status), ""),
        ])

    # --- Provenance ----------------------------------------------------------
    ws4 = wb.create_sheet("Provenance")
    ws4.column_dimensions["A"].width = 30
    ws4.column_dimensions["B"].width = 92
    basis = callable_leads[0].score.basis if callable_leads else ScoreBasis.PRIOR_UNVALIDATED
    rows = [
        ("Generated", now.strftime("%Y-%m-%d %H:%M %Z")),
        ("Scoring basis", basis.value),
        ("Commission assumed", f"${commission_per_sale_cents / 100:,.0f} first-year per issued policy"),
        ("", ""),
        ("What the scores are",
         "A relative ranking built from published industry benchmarks, most of which originate in "
         "lead-vendor marketing material. Good enough to decide who to dial first. Not a revenue forecast."),
        ("What clears that",
         "Feed real close outcomes back into Scorer(measured_close_rates=...). The basis then reads "
         "BACKTESTED instead of PRIOR_UNVALIDATED."),
        ("", ""),
        ("Data sourcing",
         "Every field here originates from the consumer's own opt-in submission or from the vendor's "
         "delivery record. Nothing is scraped, appended, or inferred about a named individual."),
        ("Why This Lead column",
         "Derived from acquisition type, lead age, resale count, and how much of the form the consumer "
         "chose to fill in. It contains no inference about anyone's health, finances, or circumstances."),
        ("", ""),
        ("Before dialing",
         "Callable status is a point-in-time result. Calling windows expire, DNC scrubs go stale at 31 "
         "days, and consent can be revoked. Re-run the gate against a live scrub before each session."),
    ]
    for i, (k, v) in enumerate(rows, start=1):
        a = ws4.cell(row=i, column=1, value=k)
        b = ws4.cell(row=i, column=2, value=v)
        a.font = Font(bold=True)
        b.alignment = Alignment(wrap_text=True, vertical="top")
        if k in ("What the scores are", "Data sourcing", "Why This Lead column", "Before dialing"):
            b.font = NOTE_FONT
        ws4.row_dimensions[i].height = 30 if len(str(v)) > 90 else 15

    return wb


def write_xlsx(scored: Sequence[ScoredLead], path: str, now: Optional[datetime] = None) -> str:
    build_workbook(scored, now=now).save(path)
    return path
