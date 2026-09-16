"""Intake normalization and scoring behavior.

The intake tests exist mostly to pin down what must never happen: a vendor
payload asserting its own DNC status, a certificate being treated as retained
because it was present, or a renamed field disappearing quietly.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.intake import normalize_record, normalize_phone  # noqa: E402
from fexlead.schema import DNCStatus, Lead, LeadType, SelfReported  # noqa: E402
from fexlead.scoring import BASE_CLOSE_RATE, ScoreBasis, Scorer  # noqa: E402

NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)


# --- intake -----------------------------------------------------------------

def test_aliases_map_across_vendor_spellings():
    a = normalize_record({"FirstName": "Pat", "Phone Number": "512-555-0147"}, "v", LeadType.AGED).lead
    b = normalize_record({"fname": "Pat", "primary_phone": "(512) 555 0147"}, "v", LeadType.AGED).lead
    assert a.first_name == b.first_name == "Pat"
    assert a.phone == b.phone == "5125550147"


def test_unmapped_fields_are_reported_not_dropped():
    """A vendor renaming a consent field must surface, not vanish."""
    res = normalize_record(
        {"first_name": "Pat", "tf_cert_url_v2": "https://cert.trustedform.com/x"}, "v", LeadType.AGED
    )
    assert "tf_cert_url_v2" in res.unmapped_fields
    assert res.lead.consent.trustedform_url is None


def test_vendor_cannot_assert_its_own_dnc_status():
    res = normalize_record(
        {"first_name": "Pat", "phone": "5125550147", "dnc_status": "clear", "dnc_checked": "2026-09-15"},
        "v", LeadType.AGED,
    )
    assert res.lead.dnc_status is DNCStatus.NOT_SCRUBBED
    assert res.lead.dnc_checked_at is None
    assert "dnc_status" in res.unmapped_fields


def test_certificate_claim_status_is_never_inferred_from_payload():
    """Presence of a cert URL says nothing about whether you retained it."""
    res = normalize_record(
        {"phone": "5125550147", "xxTrustedFormCertUrl": "https://cert.trustedform.com/abc"},
        "v", LeadType.AGED,
    )
    assert res.lead.consent.trustedform_url is not None
    assert res.lead.consent.cert_claimed is None


def test_phone_normalization():
    assert normalize_phone("1-512-555-0147") == "5125550147"
    assert normalize_phone("(512) 555.0147") == "5125550147"
    assert normalize_phone("555-0147") is None
    assert normalize_phone("") is None


def test_naive_consent_timestamp_warns_about_assumed_utc():
    res = normalize_record(
        {"phone": "5125550147", "opt_in_date": "2026-08-01 14:22:05"}, "v", LeadType.AGED
    )
    assert res.lead.consent.consent_timestamp.tzinfo is not None
    assert any("assumed UTC" in w for w in res.warnings)


def test_malformed_state_warns():
    res = normalize_record({"phone": "5125550147", "state": "Texas"}, "v", LeadType.AGED)
    assert any("not a 2-letter code" in w for w in res.warnings)


# --- scoring ----------------------------------------------------------------

def _aged(days: float, cost: int = 600, **sr) -> Lead:
    return Lead(
        lead_id=f"aged-{days}", vendor="v", lead_type=LeadType.AGED,
        cost_cents=cost, lead_created_at=NOW - timedelta(days=days),
        self_reported=SelfReported(**sr),
    )


def test_aged_leads_decay_monotonically():
    s = Scorer()
    probs = [s.score(_aged(d), NOW).p_close for d in (10, 45, 90, 200, 400)]
    assert probs == sorted(probs, reverse=True), probs


def test_unknown_vintage_is_priced_at_the_floor_not_ignored():
    s = Scorer()
    no_date = Lead(lead_id="x", vendor="v", lead_type=LeadType.AGED, cost_cents=600)
    assert s.score(no_date, NOW).p_close <= s.score(_aged(400), NOW).p_close
    assert "vintage unknown" in s.score(no_date, NOW).rationale


def test_speed_to_lead_dominates_fresh_lead_value():
    s = Scorer()
    fresh = Lead(lead_id="f", vendor="v", lead_type=LeadType.EXCLUSIVE_WEB,
                 cost_cents=3500, lead_created_at=NOW)
    fast = s.score(fresh, NOW, response_latency_minutes=3)
    slow = s.score(fresh, NOW, response_latency_minutes=45)
    assert fast.p_close > slow.p_close
    # The headline finding: a $35 lead worked slowly is worth less than it cost.
    assert fast.expected_value_cents > 0
    assert slow.expected_value_cents < 0


def test_resale_penalty_reduces_value():
    s = Scorer()
    excl = Lead(lead_id="a", vendor="v", lead_type=LeadType.SHARED_WEB,
                cost_cents=1500, lead_created_at=NOW, shared_with_count=1)
    shared = Lead(lead_id="b", vendor="v", lead_type=LeadType.SHARED_WEB,
                  cost_cents=1500, lead_created_at=NOW, shared_with_count=5)
    assert s.score(excl, NOW).p_close > s.score(shared, NOW).p_close


def test_basis_is_unvalidated_until_real_outcomes_are_supplied():
    assert Scorer().score(_aged(30), NOW).basis is ScoreBasis.PRIOR_UNVALIDATED
    backtested = Scorer(measured_close_rates={LeadType.AGED: 0.031})
    r = backtested.score(_aged(45), NOW)
    assert r.basis is ScoreBasis.BACKTESTED
    assert r.factors["base_rate"] == 0.031


def test_form_completion_depth_raises_score():
    s = Scorer()
    bare = s.score(_aged(30), NOW)
    engaged = s.score(_aged(30, optional_fields_completed=4, coverage_amount_requested=15000,
                            beneficiary_relationship="spouse"), NOW)
    assert engaged.p_close > bare.p_close
    assert "form depth" in engaged.rationale


def test_rationale_contains_no_demographic_inference():
    """The rationale must explain the score from acquisition and stated intent only.

    Two words are deliberately allowed. "aged" is a lead type -- an aged lead is
    an old lead, not an old person -- and "coverage amount" is a figure the
    consumer typed into a form. What must never appear is the consumer's own
    demographic data, or any vocabulary of inferred vulnerability.
    """
    s = Scorer()
    lead = _aged(45, age=79, optional_fields_completed=3, coverage_amount_requested=10000)
    r = s.score(lead, NOW)
    lowered = r.rationale.lower()

    forbidden = ("elderly", "senior", "widow", "widowed", "health", "illness",
                 "income", "declining", "vulnerable", "bereaved", "impaired")
    leaked = [w for w in forbidden if re.search(rf"\b{w}\b", lowered)]
    assert not leaked, f"rationale leaked {leaked}: {r.rationale}"

    # The consumer's stated age rides on the lead for underwriting fit, but must
    # never appear as a justification for why they were ranked ahead of anyone.
    assert str(lead.self_reported.age) not in r.rationale
    assert "age" not in r.factors


def test_score_is_unchanged_by_the_consumers_age():
    """Two identical leads differing only in stated age must score identically."""
    s = Scorer()
    younger = s.score(_aged(45, age=52, optional_fields_completed=2), NOW)
    older = s.score(_aged(45, age=84, optional_fields_completed=2), NOW)
    assert younger.p_close == older.p_close
    assert younger.rationale == older.rationale


def test_probability_stays_in_bounds():
    s = Scorer()
    maxed = _aged(1, optional_fields_completed=99, coverage_amount_requested=25000,
                  beneficiary_relationship="spouse")
    r = s.score(maxed, NOW)
    assert 0.0 <= r.p_close <= 1.0
    assert 0.0 <= r.score <= 100.0


def test_aged_beats_live_transfer_on_expected_value():
    """The economic thesis, asserted rather than claimed."""
    s = Scorer()
    aged = s.score(_aged(45, cost=600, optional_fields_completed=3, coverage_amount_requested=10000), NOW)
    lt = Lead(lead_id="lt", vendor="v", lead_type=LeadType.LIVE_TRANSFER,
              cost_cents=11000, lead_created_at=NOW)
    transfer = s.score(lt, NOW, response_latency_minutes=1)
    assert transfer.p_close > aged.p_close          # transfers close better
    assert aged.expected_value_cents > transfer.expected_value_cents  # aged earns more per dollar
