"""The compliance gate: mechanically blocks non-callable leads before they reach a dialer.

Every check is a pure function of (lead, context) -> CheckResult. A check that
cannot run returns UNKNOWN. The gate is callable-negative by default: a lead is
callable only if every check returned PASS.

This is deliberate. The failure mode being defended against is not a check that
returns the wrong answer, it is a check that stops running and keeps reporting
success, because absent-and-fine looks identical to present-and-fine from
outside.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Protocol, Sequence
from zoneinfo import ZoneInfo

from .schema import Check, DNCStatus, Lead

# The FTC Telemarketing Sales Rule requires the national registry to be re-scrubbed
# at least every 31 days. A scrub older than that is not a scrub.
DNC_SCRUB_MAX_AGE_DAYS = 31

# Federal TCPA calling window, in the called party's local time.
FEDERAL_WINDOW = (8, 21)  # 8:00am - 9:00pm

# State overlays that are stricter than federal. Windows are local time.
# FL (FTSA) and OK (OTSA) additionally cap commercial calls on the same subject
# at 3 per 24 hours; MD carries its own restrictions. These statutes carry
# private rights of action, which is what makes them the expensive ones.
STATE_WINDOWS = {
    "FL": (8, 20),
    "OK": (8, 20),
}
STATE_DAILY_CALL_CAP = {
    "FL": 3,
    "OK": 3,
}
# States whose mini-TCPA requires prior express written consent for any automated
# system that selects or dials, which is broader than the post-Duguid federal ATDS
# definition. Leads in these states must not be fed to an autodialer on anything
# weaker than a written consent certificate.
STRICT_PEWC_STATES = {"FL", "OK", "MD"}

# Unambiguous state -> IANA timezone. States that span more than one zone are
# deliberately absent; see AMBIGUOUS_TZ_STATES.
STATE_TZ = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "GA": "America/New_York", "HI": "Pacific/Honolulu", "IA": "America/Chicago",
    "IL": "America/Chicago", "LA": "America/Chicago", "MA": "America/New_York",
    "MD": "America/New_York", "ME": "America/New_York", "MN": "America/Chicago",
    "MO": "America/Chicago", "MS": "America/Chicago", "MT": "America/Denver",
    "NC": "America/New_York", "NH": "America/New_York", "NJ": "America/New_York",
    "NM": "America/Denver", "NV": "America/Los_Angeles", "NY": "America/New_York",
    "OH": "America/New_York", "OK": "America/Chicago", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "UT": "America/Denver",
    "VA": "America/New_York", "VT": "America/New_York", "WA": "America/Los_Angeles",
    "WI": "America/Chicago", "WV": "America/New_York", "WY": "America/Denver",
}

# States spanning multiple zones. A state code alone is not enough to place a
# call legally, so these resolve by ZIP prefix or not at all.
AMBIGUOUS_TZ_STATES = {
    "FL", "TX", "TN", "KY", "IN", "MI", "ND", "SD", "NE", "KS", "OR", "ID",
}

# Ambiguous states resolve as "default zone, with ZIP-prefix exceptions". A state
# with no default here returns UNKNOWN rather than a guess, because the cost of
# guessing wrong is a per-call statutory damages event, not a mild inaccuracy.
AMBIGUOUS_STATE_DEFAULT_TZ = {
    "TX": "America/Chicago",     # all but far west
    "FL": "America/New_York",    # all but the western panhandle
    "TN": "America/Chicago",     # middle and west
}

# ZIP-prefix exceptions to the defaults above. Prefixes for ambiguous states with
# no default (KY, IN, MI, ND, SD, NE, KS, OR, ID) are intentionally not modeled;
# those resolve UNKNOWN until a licensed ZIP-to-timezone dataset is wired in.
ZIP_PREFIX_TZ = {
    # Far west Texas is Mountain.
    "798": "America/Denver", "799": "America/Denver", "885": "America/Denver",
    # Florida's western panhandle is Central. Tallahassee (323) is Eastern and
    # falls through to the state default.
    "324": "America/Chicago", "325": "America/Chicago",
    # East Tennessee is Eastern.
    "373": "America/New_York", "374": "America/New_York", "376": "America/New_York",
    "377": "America/New_York", "378": "America/New_York", "379": "America/New_York",
}


@dataclass
class CheckResult:
    """Outcome of one named check, with the reason attached.

    The reason is not decoration. When a lead is blocked, the reason is what
    makes the block auditable six months later.
    """

    name: str
    status: Check
    reason: str

    @property
    def is_pass(self) -> bool:
        return self.status is Check.PASS


@dataclass
class GateResult:
    lead_id: str
    checks: list[CheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evaluated_at: Optional[datetime] = None

    @property
    def callable_now(self) -> bool:
        """True only if every check ran and every check passed."""
        return bool(self.checks) and all(c.is_pass for c in self.checks)

    @property
    def blocking(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is Check.BLOCK]

    @property
    def unknown(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is Check.UNKNOWN]

    def summary(self) -> str:
        if self.callable_now:
            return "CALLABLE"
        parts = []
        if self.blocking:
            parts.append("BLOCKED: " + "; ".join(f"{c.name} ({c.reason})" for c in self.blocking))
        if self.unknown:
            parts.append("UNKNOWN: " + "; ".join(f"{c.name} ({c.reason})" for c in self.unknown))
        return " | ".join(parts)


class SuppressionSource(Protocol):
    """A source of internally suppressed numbers (prior opt-outs, complaints).

    Implementations must raise rather than return an empty set when the
    underlying store is unreachable. An empty suppression list and an
    unreachable suppression list must not produce the same call decision.
    """

    def contains(self, phone: str) -> bool: ...


class CallHistorySource(Protocol):
    """Counts prior calls to a number within a rolling window, for state caps."""

    def calls_in_last_24h(self, phone: str, subject: str) -> int: ...


def resolve_timezone(lead: Lead) -> Optional[ZoneInfo]:
    """Best-effort timezone for the called party. None means we do not know.

    Resolution order: ZIP-prefix exception, then the state default (for both
    single-zone and modeled multi-zone states), then None. Returning None rather
    than guessing is the point -- placing a call outside the legal window because
    a state-level guess was wrong is a per-call statutory damages event.

    Note: Arizona does not observe DST, which ZoneInfo handles, but the Navajo
    Nation within Arizona does. Leads in that area will be off by an hour during
    DST and should be resolved from a finer-grained source.
    """
    state = (lead.state or "").upper().strip()
    zip3 = (lead.postal_code or "").strip()[:3]

    if zip3 and zip3 in ZIP_PREFIX_TZ:
        return ZoneInfo(ZIP_PREFIX_TZ[zip3])
    if state in AMBIGUOUS_STATE_DEFAULT_TZ:
        return ZoneInfo(AMBIGUOUS_STATE_DEFAULT_TZ[state])
    if state in AMBIGUOUS_TZ_STATES:
        return None
    if state in STATE_TZ:
        return ZoneInfo(STATE_TZ[state])
    return None


def check_consent(lead: Lead, now: datetime) -> CheckResult:
    """Require documented, provable consent before any outbound marketing call."""
    c = lead.consent
    if not c.has_certificate():
        return CheckResult(
            "consent",
            Check.UNKNOWN,
            "no TrustedForm certificate or Jornaya LeadiD on the record",
        )
    if c.consent_timestamp is None:
        return CheckResult("consent", Check.UNKNOWN, "certificate present but no consent timestamp")
    if c.consent_language is None:
        return CheckResult("consent", Check.UNKNOWN, "certificate present but consent language not captured")
    if c.trustedform_url and c.cert_claimed is False:
        return CheckResult(
            "consent",
            Check.BLOCK,
            "TrustedForm certificate was never claimed, so the URL no longer proves consent",
        )
    if c.trustedform_url and c.cert_claimed is None:
        return CheckResult("consent", Check.UNKNOWN, "TrustedForm claim status unknown")
    return CheckResult("consent", Check.PASS, "written consent documented and retained")


def check_dnc(lead: Lead, now: datetime) -> CheckResult:
    """Federal and state Do Not Call registry status, with a freshness requirement."""
    if lead.dnc_status is DNCStatus.NOT_SCRUBBED:
        return CheckResult("dnc", Check.UNKNOWN, "number has never been scrubbed")
    if lead.dnc_checked_at is None:
        return CheckResult("dnc", Check.UNKNOWN, "scrub result present but no scrub timestamp")

    age_days = (now - lead.dnc_checked_at).total_seconds() / 86400.0
    if age_days > DNC_SCRUB_MAX_AGE_DAYS:
        return CheckResult(
            "dnc",
            Check.UNKNOWN,
            f"scrub is {age_days:.0f} days old, exceeds the {DNC_SCRUB_MAX_AGE_DAYS}-day TSR requirement",
        )
    if lead.dnc_status in (DNCStatus.ON_FEDERAL_DNC, DNCStatus.ON_STATE_DNC, DNCStatus.ON_INTERNAL_DNC):
        return CheckResult("dnc", Check.BLOCK, f"number is {lead.dnc_status.value}")
    return CheckResult("dnc", Check.PASS, f"clear as of {lead.dnc_checked_at.isoformat()}")


def check_internal_suppression(
    lead: Lead, now: datetime, source: Optional[SuppressionSource]
) -> CheckResult:
    """Honor prior opt-outs. An unreachable suppression store is never a pass.

    This is the check that reproduces the original bug class: a gate whose data
    dependency fails and which then reports success for everything downstream of
    the failure.
    """
    if source is None:
        return CheckResult("internal_suppression", Check.UNKNOWN, "no suppression source configured")
    if not lead.phone:
        return CheckResult("internal_suppression", Check.UNKNOWN, "lead has no phone number")
    try:
        hit = source.contains(lead.phone)
    except Exception as exc:  # noqa: BLE001 - any failure to read is UNKNOWN, not PASS
        return CheckResult("internal_suppression", Check.UNKNOWN, f"suppression store unreadable: {exc}")
    if hit:
        return CheckResult("internal_suppression", Check.BLOCK, "number previously opted out")
    return CheckResult("internal_suppression", Check.PASS, "not on internal suppression list")


def check_litigator(lead: Lead, now: datetime) -> CheckResult:
    """Known TCPA serial plaintiffs. None means not screened, which is not clear."""
    if lead.litigator_flag is None:
        return CheckResult("litigator", Check.UNKNOWN, "number not screened against litigator database")
    if lead.litigator_flag:
        return CheckResult("litigator", Check.BLOCK, "number belongs to a known TCPA litigator")
    return CheckResult("litigator", Check.PASS, "not a known litigator")


def check_calling_window(lead: Lead, now: datetime) -> CheckResult:
    """Enforce the calling window in the called party's local time, not the agent's."""
    tz = resolve_timezone(lead)
    if tz is None:
        return CheckResult(
            "calling_window",
            Check.UNKNOWN,
            f"cannot resolve local timezone from state={lead.state!r} zip={lead.postal_code!r}",
        )
    state = (lead.state or "").upper().strip()
    start, end = STATE_WINDOWS.get(state, FEDERAL_WINDOW)
    local = now.astimezone(tz)
    if start <= local.hour < end:
        return CheckResult(
            "calling_window",
            Check.PASS,
            f"{local.strftime('%H:%M %Z')} is inside the {start:02d}:00-{end:02d}:00 window",
        )
    return CheckResult(
        "calling_window",
        Check.BLOCK,
        f"{local.strftime('%H:%M %Z')} is outside the {start:02d}:00-{end:02d}:00 window",
    )


def check_state_frequency_cap(
    lead: Lead, now: datetime, history: Optional[CallHistorySource], subject: str
) -> CheckResult:
    """FL and OK cap commercial calls on the same subject at 3 per 24 hours."""
    state = (lead.state or "").upper().strip()
    cap = STATE_DAILY_CALL_CAP.get(state)
    if cap is None:
        return CheckResult("state_frequency_cap", Check.PASS, f"{state or 'unknown state'} has no daily cap")
    if history is None:
        return CheckResult(
            "state_frequency_cap",
            Check.UNKNOWN,
            f"{state} caps at {cap}/24h but no call history source is configured",
        )
    if not lead.phone:
        return CheckResult("state_frequency_cap", Check.UNKNOWN, "lead has no phone number")
    try:
        count = history.calls_in_last_24h(lead.phone, subject)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("state_frequency_cap", Check.UNKNOWN, f"call history unreadable: {exc}")
    if count >= cap:
        return CheckResult(
            "state_frequency_cap", Check.BLOCK, f"{count} calls in last 24h meets {state} cap of {cap}"
        )
    return CheckResult("state_frequency_cap", Check.PASS, f"{count}/{cap} calls used in {state}")


@dataclass
class ComplianceGate:
    """Runs every check and refuses to emit a pass unless all of them passed."""

    suppression: Optional[SuppressionSource] = None
    call_history: Optional[CallHistorySource] = None
    subject: str = "final_expense"
    # Consent older than this does not block, but is surfaced as a warning: TCPA
    # consent has no statutory expiry, yet the burden of proving consent existed
    # at the time of the call rests on the caller, and that burden gets heavier
    # with age.
    consent_stale_warning_days: int = 180

    def evaluate(self, lead: Lead, now: Optional[datetime] = None) -> GateResult:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("evaluate() requires a timezone-aware datetime")

        result = GateResult(lead_id=lead.lead_id, evaluated_at=now)
        result.checks = [
            check_consent(lead, now),
            check_dnc(lead, now),
            check_internal_suppression(lead, now, self.suppression),
            check_litigator(lead, now),
            check_calling_window(lead, now),
            check_state_frequency_cap(lead, now, self.call_history, self.subject),
        ]

        ts = lead.consent.consent_timestamp
        if ts is not None:
            age = (now - ts).days
            if age > self.consent_stale_warning_days:
                result.warnings.append(
                    f"consent is {age} days old; evidentiary weight decays even though consent does not expire"
                )
        state = (lead.state or "").upper().strip()
        if state in STRICT_PEWC_STATES and not lead.consent.has_certificate():
            result.warnings.append(
                f"{state} requires prior express written consent for automated dialing; manual dial only"
            )
        return result

    def partition(
        self, leads: Sequence[Lead], now: Optional[datetime] = None
    ) -> tuple[list[tuple[Lead, GateResult]], list[tuple[Lead, GateResult]]]:
        """Split leads into (callable, not_callable). Nothing is dropped silently."""
        callable_leads: list[tuple[Lead, GateResult]] = []
        held: list[tuple[Lead, GateResult]] = []
        for lead in leads:
            res = self.evaluate(lead, now)
            (callable_leads if res.callable_now else held).append((lead, res))
        return callable_leads, held
