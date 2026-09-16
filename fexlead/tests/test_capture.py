"""First-party lead capture: what makes a lead sellable, and what refuses to.

The one property that matters: a capture with no consent certificate is never
marked sellable, no matter how complete the rest of the form is. Consent is the
product; without it there is nothing to sell.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.capture import STANDARD_CONSENT_TEMPLATE, lead_from_capture  # noqa: E402
from fexlead.compliance import ComplianceGate  # noqa: E402
from fexlead.schema import Check, DNCStatus, LeadType, ReassignedStatus  # noqa: E402

NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)
COMPANY = "Lone Star Final Expense"
SHOWN = STANDARD_CONSENT_TEMPLATE.format(company=COMPANY)

COMPLETE_FORM = {
    "first_name": "Pat", "last_name": "Rivera", "phone": "(512) 555-0147",
    "email": "pat.rivera@gmail.com", "state": "TX", "postal_code": "78701",
    "age": "68", "coverage_amount": "10000", "beneficiary_relationship": "spouse",
}


def capture(**kw):
    args = dict(company=COMPANY, consent_language_shown=SHOWN, now=NOW)
    args.update(kw)
    return lead_from_capture(COMPLETE_FORM, **args)


def test_complete_optin_with_certificate_is_sellable():
    r = capture(trustedform_token="https://cert.trustedform.com/tok", ip_address="203.0.113.7")
    assert r.sellable is True
    assert r.lead.lead_type is LeadType.EXCLUSIVE_WEB
    assert r.lead.shared_with_count == 1
    assert r.lead.consent.trustedform_url == "https://cert.trustedform.com/tok"
    assert r.lead.consent.consent_timestamp == NOW


def test_no_certificate_is_never_sellable():
    r = capture()  # no token at all
    assert r.sellable is False
    assert any("no consent certificate" in x for x in r.reasons)


def test_no_consent_language_is_never_sellable():
    r = lead_from_capture(COMPLETE_FORM, company=COMPANY, consent_language_shown="",
                          trustedform_token="https://cert.trustedform.com/tok", now=NOW)
    assert r.sellable is False
    assert any("no consent language" in x for x in r.reasons)


def test_jornaya_token_alone_is_sellable():
    r = capture(jornaya_token="A1B2C3D4E5F6A7B8")
    assert r.sellable is True
    assert r.lead.consent.jornaya_leadid == "A1B2C3D4E5F6A7B8"


def test_invalid_phone_is_not_sellable():
    form = dict(COMPLETE_FORM, phone="555")
    r = lead_from_capture(form, company=COMPANY, consent_language_shown=SHOWN,
                          trustedform_token="https://cert.trustedform.com/tok", now=NOW)
    assert r.sellable is False


def test_capture_never_pre_scrubs():
    """A freshly captured lead has not been scrubbed; the pipeline does that before sale."""
    r = capture(trustedform_token="https://cert.trustedform.com/tok")
    assert r.lead.dnc_status is DNCStatus.NOT_SCRUBBED
    assert r.lead.reassigned_status is ReassignedStatus.NOT_QUERIED


def test_under_50_is_captured_but_flagged():
    form = dict(COMPLETE_FORM, age="41")
    r = lead_from_capture(form, company=COMPANY, consent_language_shown=SHOWN,
                          trustedform_token="https://cert.trustedform.com/tok", now=NOW)
    assert r.lead is not None
    assert any("under the 50+ target" in x for x in r.reasons)


def test_cert_claimed_is_not_assumed_true():
    """Born unclaimed unless the server actually claimed it. Claiming is a real API call."""
    r = capture(trustedform_token="https://cert.trustedform.com/tok")
    assert r.lead.consent.cert_claimed is None


def test_captured_lead_flows_through_the_gate():
    """End to end: a captured lead, once scrubbed, is callable by the same gate."""
    from datetime import timedelta
    r = capture(trustedform_token="https://cert.trustedform.com/tok")
    lead = r.lead
    # simulate the scrub step the pipeline runs before sale/dial
    lead.dnc_status = DNCStatus.CLEAR
    lead.dnc_checked_at = NOW - timedelta(days=1)
    lead.litigator_flag = False
    lead.reassigned_status = ReassignedStatus.SAME_SUBSCRIBER
    lead.reassigned_checked_at = NOW - timedelta(days=1)
    lead.consent.cert_claimed = True
    res = ComplianceGate().evaluate(lead, NOW)
    # consent, dnc, litigator, reassigned, window all fine; suppression UNKNOWN only
    # because no store is configured in this bare gate.
    statuses = {c.name: c.status for c in res.checks}
    assert statuses["consent"] is Check.PASS
    assert statuses["reassigned_number"] is Check.PASS
    assert statuses["calling_window"] is Check.PASS
