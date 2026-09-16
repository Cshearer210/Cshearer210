"""End-to-end demo: generate synthetic leads, gate them, score them, export.

    python -m fexlead.cli --out call_sheet.xlsx --count 100

Swap generate() for intake.from_csv() or intake.from_payloads() to run real leads
through the same path. Nothing else changes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .compliance import ComplianceGate
from .export import ScoredLead, write_xlsx
from .sample import generate
from .scoring import Scorer
from .scrub import InMemoryDNC, InMemoryLitigator, InMemoryReassigned, ScrubRunner
from .verification import verify_lead


class InMemorySuppression:
    def __init__(self, numbers: set[str] | None = None) -> None:
        self.numbers = numbers or set()

    def contains(self, phone: str) -> bool:
        return phone in self.numbers


class InMemoryCallHistory:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def calls_in_last_24h(self, phone: str, subject: str) -> int:
        return self.counts.get(phone, 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="call_sheet.xlsx")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--commission", type=int, default=70_000, help="first-year commission per sale, in cents")
    ap.add_argument("--at", default=None,
                    help="ISO8601 instant to evaluate against, e.g. 2026-09-16T17:00:00+00:00. "
                         "Defaults to now. Calling-window results depend on this.")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    leads = generate(args.count, now=now)

    # Demonstrate the scrub step. Real adapters replace these three mocks; the
    # rest of the pipeline does not change. A number the mock cannot reach is
    # left unscrubbed, and the gate holds it.
    scrub = ScrubRunner(dnc=InMemoryDNC(), litigator=InMemoryLitigator(), reassigned=InMemoryReassigned())
    report = scrub.scrub(leads, now)

    gate = ComplianceGate(suppression=InMemorySuppression(), call_history=InMemoryCallHistory())
    scorer = Scorer(commission_per_sale_cents=args.commission)

    # Deliverability is DNS-bound; keep it off for a fast, deterministic demo.
    # In production leave it on so a dead email domain is caught.
    scored = []
    for lead in leads:
        g = gate.evaluate(lead, now)
        q = verify_lead(lead, check_deliverability=False)
        s = scorer.score(lead, now) if g.callable_now else None
        scored.append(ScoredLead(lead=lead, gate=g, score=s, quality=q))

    write_xlsx(scored, args.out, now=now)

    callable_n = sum(1 for s in scored if s.gate.callable_now)
    blocked_n = sum(1 for s in scored if s.gate.blocking)
    unknown_n = sum(1 for s in scored if not s.gate.blocking and s.gate.unknown)
    spend = sum(l.cost_cents or 0 for l in leads) / 100
    ev = sum(s.score.expected_value_cents for s in scored if s.score) / 100

    print(f"{len(leads)} leads in, evaluated at {now.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  scrub: {report.summary()}")
    print(f"  callable : {callable_n}")
    print(f"  held (fixable, UNKNOWN) : {unknown_n}")
    print(f"  held (hard BLOCK)       : {blocked_n}")
    print(f"  lead spend represented  : ${spend:,.2f}")
    print(f"  expected value, callable only : ${ev:,.2f}")
    from collections import Counter
    grades = Counter(s.quality.grade() for s in scored if s.quality)
    print(f"  data quality (all leads): " + ", ".join(f"{g}:{grades[g]}" for g in sorted(grades)))
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
