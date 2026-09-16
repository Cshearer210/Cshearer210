"""Expected-value scoring for final expense leads.

Two rules govern this module.

First, scores are built only from what the consumer told you and from how the
lead was acquired. Nothing here infers health, bereavement, cognitive state or
financial distress about a named individual. That line is not stylistic: a model
that ranks seniors by inferred vulnerability is the thing regulators, carriers
and plaintiffs' lawyers all treat differently from a model that ranks them by
how completely they filled in your form.

Second, every constant below is a published industry benchmark, not a measured
fact about this book of business. They are labeled PRIOR_UNVALIDATED and stay
that way until backtested against real close outcomes. Most of them originate in
lead-vendor marketing material, which has an obvious incentive to inflate. They
are good enough to rank leads relative to each other and not good enough to
forecast revenue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .schema import Lead, LeadType


class ScoreBasis(str, Enum):
    """Where a score's numbers came from. Never let these read the same."""

    PRIOR_UNVALIDATED = "PRIOR_UNVALIDATED"   # published benchmarks, nothing measured
    BACKTESTED = "BACKTESTED"                 # fitted to this book's real outcomes


# Baseline probability that one lead of this type becomes one issued policy.
# These are per-lead, not per-appointment. The distinction matters: "35-50% close
# on sits" is a widely quoted direct mail figure with a completely different
# denominator, and mixing the two inflates direct mail by roughly a factor of
# three. Everything here is per-lead.
BASE_CLOSE_RATE = {
    LeadType.LIVE_TRANSFER: 0.20,
    LeadType.EXCLUSIVE_WEB: 0.10,
    LeadType.DIRECT_MAIL: 0.12,
    LeadType.SHARED_WEB: 0.05,
    LeadType.TELEMARKETED: 0.06,
    LeadType.AGED: 0.05,
}

# Aged leads decay by vintage. Applied only to LeadType.AGED.
AGED_DECAY = [
    (30, 1.20),    # 0-30 days: still warm
    (60, 1.00),    # 30-60 days: the 4-6% band, this is the reference point
    (120, 0.50),   # 60-120 days: the 2-3% band
    (365, 0.30),
    (float("inf"), 0.20),
]

# Speed to lead. The single largest controllable multiplier on a fresh lead, and
# the one an automated pipeline is actually positioned to win. Not applied to
# aged leads, whose vintage is already priced in above.
LATENCY_MULTIPLIER = [
    (5, 1.00),
    (15, 0.75),
    (30, 0.50),
    (120, 0.35),
    (float("inf"), 0.25),
]

# Each additional buyer of the same lead. Derived from the reported drop in
# contact rate when a lead is resold to roughly five buyers.
SHARED_PENALTY_PER_EXTRA_BUYER = 0.30

DEFAULT_COMMISSION_PER_SALE_CENTS = 70_000  # $700 first-year, midpoint of $500-$1,200


def _bucket(value: float, table: list[tuple[float, float]]) -> float:
    for threshold, multiplier in table:
        if value <= threshold:
            return multiplier
    return table[-1][1]


@dataclass
class ScoreResult:
    lead_id: str
    score: float                       # 0-100, for ranking only
    p_close: float
    expected_value_cents: int          # expected commission net of lead cost
    basis: ScoreBasis
    rationale: str
    factors: dict[str, float] = field(default_factory=dict)


@dataclass
class Scorer:
    commission_per_sale_cents: int = DEFAULT_COMMISSION_PER_SALE_CENTS
    basis: ScoreBasis = ScoreBasis.PRIOR_UNVALIDATED
    # Set once real outcomes exist. Until then the scorer will not claim to be
    # anything other than a ranking heuristic built on other people's marketing.
    measured_close_rates: Optional[dict[LeadType, float]] = None

    def __post_init__(self) -> None:
        if self.measured_close_rates:
            self.basis = ScoreBasis.BACKTESTED

    def _base_rate(self, lead: Lead) -> float:
        if self.measured_close_rates and lead.lead_type in self.measured_close_rates:
            return self.measured_close_rates[lead.lead_type]
        return BASE_CLOSE_RATE.get(lead.lead_type, 0.05)

    def score(
        self,
        lead: Lead,
        now: Optional[datetime] = None,
        response_latency_minutes: Optional[float] = None,
    ) -> ScoreResult:
        now = now or datetime.now(timezone.utc)
        factors: dict[str, float] = {}
        reasons: list[str] = []

        p = self._base_rate(lead)
        factors["base_rate"] = p
        reasons.append(f"{lead.lead_type.value} base {p:.0%}")

        # Vintage, for aged leads only.
        if lead.lead_type is LeadType.AGED:
            age = lead.age_days(now)
            if age is None:
                # Unknown vintage is priced as the worst case rather than ignored.
                m = AGED_DECAY[-1][1]
                reasons.append("vintage unknown, priced at floor")
            else:
                m = _bucket(age, AGED_DECAY)
                reasons.append(f"{age:.0f}d vintage x{m:.2f}")
            factors["vintage"] = m
            p *= m

        # Speed to lead, for fresh leads only.
        if lead.lead_type is not LeadType.AGED and response_latency_minutes is not None:
            m = _bucket(response_latency_minutes, LATENCY_MULTIPLIER)
            factors["latency"] = m
            p *= m
            reasons.append(f"{response_latency_minutes:.0f}min response x{m:.2f}")

        # Resale competition.
        if lead.shared_with_count:
            extra = max(0, lead.shared_with_count - 1)
            m = 1.0 / (1.0 + SHARED_PENALTY_PER_EXTRA_BUYER * extra)
            factors["shared"] = m
            p *= m
            reasons.append(f"shared with {lead.shared_with_count} x{m:.2f}")

        # Stated intent, from the consumer's own form entries only.
        sr = lead.self_reported
        intent = 1.0
        if sr.optional_fields_completed is not None:
            bump = min(0.25, 0.05 * sr.optional_fields_completed)
            intent += bump
            if bump:
                reasons.append(f"+{bump:.0%} form depth ({sr.optional_fields_completed} optional fields)")
        if sr.coverage_amount_requested:
            intent += 0.10
            reasons.append("+10% named a coverage amount")
        if sr.beneficiary_relationship:
            intent += 0.05
            reasons.append("+5% named a beneficiary")
        if sr.has_existing_coverage is True:
            # Already owns coverage: understands the product, but needs less.
            intent -= 0.10
            reasons.append("-10% already has coverage")
        factors["intent"] = intent
        p *= intent

        p = max(0.0, min(1.0, p))

        gross = p * self.commission_per_sale_cents
        ev = int(round(gross - (lead.cost_cents or 0)))

        # Score is a rank, normalized against the best realistic case rather than
        # against 1.0, which no lead approaches.
        score = round(min(100.0, (p / 0.25) * 100.0), 1)

        return ScoreResult(
            lead_id=lead.lead_id,
            score=score,
            p_close=round(p, 4),
            expected_value_cents=ev,
            basis=self.basis,
            rationale="; ".join(reasons),
            factors=factors,
        )
