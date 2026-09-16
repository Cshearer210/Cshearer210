"""Canonical lead record and the tri-state primitives the rest of the package uses.

Design rule carried through every module: absent-and-fine and present-and-fine must
never produce the same output. A check that could not run returns UNKNOWN, and
UNKNOWN is never a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from typing import Optional


class Check(str, Enum):
    """Result of a single compliance check.

    PASS    - the check ran and the lead is clear on this dimension.
    BLOCK   - the check ran and the lead is not callable.
    UNKNOWN - the check could not run (missing data, stale scrub, unreachable
              provider). Never a pass. This exists because the failure mode that
              matters is a gate that silently degrades to allowing everything.
    """

    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


class LeadType(str, Enum):
    """How the lead was acquired. Drives both scoring priors and cost basis."""

    EXCLUSIVE_WEB = "exclusive_web"
    SHARED_WEB = "shared_web"
    AGED = "aged"
    DIRECT_MAIL = "direct_mail"
    LIVE_TRANSFER = "live_transfer"
    TELEMARKETED = "telemarketed"


class DNCStatus(str, Enum):
    """Outcome of a Do Not Call scrub.

    NOT_SCRUBBED is deliberately distinct from CLEAR. A record that was never
    checked must not read the same as a record that was checked and came back
    clean.
    """

    CLEAR = "clear"
    ON_FEDERAL_DNC = "on_federal_dnc"
    ON_STATE_DNC = "on_state_dnc"
    ON_INTERNAL_DNC = "on_internal_dnc"
    NOT_SCRUBBED = "not_scrubbed"


@dataclass
class Consent:
    """Proof that the consumer asked to be contacted.

    Every field here is evidence in a TCPA defense. The certificate URL is the
    primary artifact; everything else corroborates it. None means "we do not
    have this", which the gate treats as UNKNOWN rather than as absence of a
    problem.
    """

    trustedform_url: Optional[str] = None
    jornaya_leadid: Optional[str] = None
    consent_timestamp: Optional[datetime] = None
    consent_language: Optional[str] = None
    source_url: Optional[str] = None
    ip_address: Optional[str] = None
    # TrustedForm certificates must be claimed to be retained past their default
    # window. An unclaimed cert that has aged out is a URL that no longer proves
    # anything, so we track the claim explicitly rather than assuming.
    cert_claimed: Optional[bool] = None

    def has_certificate(self) -> bool:
        return bool(self.trustedform_url or self.jornaya_leadid)


@dataclass
class SelfReported:
    """Facts the consumer volunteered on the opt-in form.

    Self-disclosure only. Nothing in this class may be inferred, modeled, or
    appended from a third-party file. The distinction is not stylistic: a
    consumer telling you their age bracket on a quote form is data they chose to
    give you, while an appended health or financial-distress score on a named
    individual is the thing that turns a lead list into an elder-targeting list.
    """

    age: Optional[int] = None
    date_of_birth: Optional[date] = None
    coverage_amount_requested: Optional[int] = None
    has_existing_coverage: Optional[bool] = None
    tobacco_use: Optional[bool] = None
    beneficiary_relationship: Optional[str] = None
    # Number of optional fields the consumer filled in beyond the required
    # minimum. Form-completion depth is one of the few honest intent signals.
    optional_fields_completed: Optional[int] = None


@dataclass
class Lead:
    """One final expense lead, normalized across vendors."""

    lead_id: str
    vendor: str
    lead_type: LeadType

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None

    consent: Consent = field(default_factory=Consent)
    self_reported: SelfReported = field(default_factory=SelfReported)

    vendor_lead_id: Optional[str] = None
    lead_created_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    cost_cents: Optional[int] = None
    # How many other agents bought this same lead. None means the vendor did not
    # say, which is materially different from 0.
    shared_with_count: Optional[int] = None

    dnc_status: DNCStatus = DNCStatus.NOT_SCRUBBED
    dnc_checked_at: Optional[datetime] = None
    litigator_flag: Optional[bool] = None

    def age_days(self, now: Optional[datetime] = None) -> Optional[float]:
        """Days since the consumer submitted the form. None if we do not know."""
        if self.lead_created_at is None:
            return None
        now = now or datetime.now(self.lead_created_at.tzinfo)
        return (now - self.lead_created_at).total_seconds() / 86400.0

    def full_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts)

    def to_dict(self) -> dict:
        return asdict(self)
