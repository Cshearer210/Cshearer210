"""CAN-SPAM message validation, suppression, and the send guard.

The message validator is itself a gate, so it gets the same treatment as the call
gate: every check is made to fail on purpose, and a meta-test asserts each was seen
passing and failing at least once.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.email_compliance import (  # noqa: E402
    DryRunSender, EmailCampaign, EmailMessage, SuppressionList,
    business_days_between, validate_message,
)
from fexlead.schema import Check  # noqa: E402

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)  # a Wednesday

OBSERVED: dict[str, set[Check]] = defaultdict(set)


def _record(validation):
    for c in validation.checks:
        OBSERVED[c.name].add(c.status)
    return validation


def good_message(**overrides) -> EmailMessage:
    base = dict(
        from_name="Chris Shearer",
        from_email="chris@example.com",
        subject="Final expense coverage options for Texas residents over 50",
        body="This is an advertisement. Affordable burial and final expense coverage.",
        physical_postal_address="123 Congress Ave, Austin, TX 78701",
        unsubscribe_url="https://example.com/unsubscribe?id=abc",
        identifies_as_ad=True,
    )
    base.update(overrides)
    return EmailMessage(**base)


def status_of(validation, name: str) -> Check:
    return next(c.status for c in validation.checks if c.name == name)


# --- the baseline -----------------------------------------------------------

def test_compliant_message_is_sendable():
    v = _record(validate_message(good_message()))
    assert v.sendable, v.summary()


# --- each check made to fail ------------------------------------------------

def test_missing_from_name_blocks():
    v = _record(validate_message(good_message(from_name="")))
    assert status_of(v, "from_line") is Check.BLOCK


def test_deceptive_subject_blocks():
    v = _record(validate_message(good_message(subject="Re: your policy payment is due")))
    assert status_of(v, "subject") is Check.BLOCK


def test_fake_forward_subject_blocks():
    v = _record(validate_message(good_message(subject="Fwd: important account update")))
    assert status_of(v, "subject") is Check.BLOCK


def test_missing_ad_disclosure_blocks():
    v = _record(validate_message(good_message(identifies_as_ad=False, body="Affordable coverage, call today.")))
    assert status_of(v, "ad_disclosure") is Check.BLOCK


def test_ad_disclosure_in_body_passes_without_flag():
    v = _record(validate_message(good_message(identifies_as_ad=False,
                                              body="This is a paid advertisement for coverage.")))
    assert status_of(v, "ad_disclosure") is Check.PASS


def test_missing_physical_address_blocks():
    v = _record(validate_message(good_message(physical_postal_address="")))
    assert status_of(v, "physical_address") is Check.BLOCK


def test_incomplete_physical_address_is_unknown():
    """Present but implausible: hold and verify rather than assume valid or invalid."""
    v = _record(validate_message(good_message(physical_postal_address="Austin TX")))
    assert status_of(v, "physical_address") is Check.UNKNOWN


def test_missing_optout_blocks():
    v = _record(validate_message(good_message(unsubscribe_url=None, unsubscribe_email=None)))
    assert status_of(v, "optout") is Check.BLOCK


def test_optout_via_email_passes():
    v = _record(validate_message(good_message(unsubscribe_url=None, unsubscribe_email="stop@example.com")))
    assert status_of(v, "optout") is Check.PASS


# --- suppression and the send guard -----------------------------------------

def test_suppressed_recipient_is_never_emailed():
    sup = SuppressionList()
    sup.opt_out("stop@example.com")
    sender = DryRunSender()
    res = EmailCampaign(sender, sup).send(good_message(), ["ok@example.com", "stop@example.com"])
    assert res.sent == 1
    assert res.suppressed == 1
    assert "stop@example.com" not in sender.sent


def test_noncompliant_message_goes_to_nobody():
    """One bad message must not reach a single recipient."""
    sender = DryRunSender()
    res = EmailCampaign(sender, SuppressionList()).send(
        good_message(physical_postal_address=""), ["a@example.com", "b@example.com"])
    assert res.sent == 0
    assert res.blocked_message is not None
    assert sender.sent == []


def test_optout_is_case_insensitive():
    sup = SuppressionList()
    sup.opt_out("Stop@Example.com")
    assert sup.is_suppressed("stop@example.com")


def test_invalid_addresses_are_counted_not_sent():
    sender = DryRunSender()
    res = EmailCampaign(sender, SuppressionList()).send(good_message(), ["good@example.com", "no-at-sign"])
    assert res.sent == 1
    assert res.invalid_address == 1


# --- business-day math and the honor-window audit ---------------------------

def test_business_days_skip_weekends():
    # Fri -> Mon is one business day.
    fri = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    assert business_days_between(fri, mon) == 1
    # Two full weeks is 10 business days.
    assert business_days_between(NOW, NOW + timedelta(days=14)) == 10


def test_overdue_audit_is_empty_with_immediate_suppression():
    sup = SuppressionList()
    sup.opt_out("stop@example.com", when=NOW - timedelta(days=3))
    assert sup.overdue(NOW) == []


def test_overdue_audit_detects_a_violation():
    """The audit must be able to fire, or it proves nothing."""
    sup = SuppressionList()
    sup.opt_out("stale@example.com", when=NOW - timedelta(days=21))  # >10 business days ago
    overdue = sup.overdue(NOW)
    assert len(overdue) == 1
    assert overdue[0].email == "stale@example.com"


# --- meta-test --------------------------------------------------------------

def test_every_message_check_seen_passing_and_failing():
    expected = {"from_line", "subject", "ad_disclosure", "physical_address", "optout"}
    missing = expected - OBSERVED.keys()
    assert not missing, f"checks never exercised: {sorted(missing)}"
    incomplete = {
        name: sorted(s.value for s in ({Check.PASS, Check.BLOCK} - statuses))
        for name, statuses in OBSERVED.items()
        if name in expected and {Check.PASS, Check.BLOCK} - statuses
    }
    assert not incomplete, f"checks never seen both passing and blocking: {incomplete}"
