"""Contact-data verification, and the property that keeps it honest.

A deliverability check that cannot run (DNS unreachable) must return UNKNOWN, not
PASS. Accuracy you could not confirm is not accuracy. The offline test forces that
path by monkeypatching the validator to raise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fexlead.verification as V  # noqa: E402
from fexlead.schema import Check, Lead, LeadType  # noqa: E402
from fexlead.verification import verify_email, verify_lead, verify_phone  # noqa: E402


def lead(**kw) -> Lead:
    base = dict(lead_id="x", vendor="v", lead_type=LeadType.AGED)
    base.update(kw)
    return Lead(**base)


# --- phone ------------------------------------------------------------------

def test_valid_number_passes_and_reports_timezone():
    r = verify_phone("5125550147")
    assert r.status is Check.PASS
    assert r.extra["area_code_timezone"] == "America/Chicago"


def test_too_long_number_blocks():
    assert verify_phone("5125551234567").status is Check.BLOCK


def test_missing_phone_is_unknown_not_block():
    """No phone is 'we cannot check', which differs from a phone proven invalid."""
    assert verify_phone(None).status is Check.UNKNOWN


def test_toll_free_number_is_flagged_unknown():
    r = verify_phone("8005550147")  # toll-free is implausible for a residential prospect
    assert r.status is Check.UNKNOWN
    assert "toll_free" in r.detail


# --- email ------------------------------------------------------------------

def test_valid_syntax_passes_when_deliverability_skipped_is_unknown():
    r = verify_email("pat@example.com", check_deliverability=False)
    assert r.status is Check.UNKNOWN  # syntax fine, but deliverability not confirmed
    assert "not checked" in r.detail


def test_malformed_email_blocks():
    assert verify_email("not-an-email", check_deliverability=False).status is Check.BLOCK


def test_missing_email_is_unknown():
    assert verify_email(None).status is Check.UNKNOWN


def test_deliverability_outage_is_unknown_not_pass(monkeypatch):
    """The core honesty property: a DNS failure must not read as a clean email."""
    def boom(*a, **k):
        if k.get("check_deliverability"):
            raise OSError("DNS unreachable")
        return True  # syntax passes
    monkeypatch.setattr(V, "validate_email", boom)
    r = verify_email("pat@example.com", check_deliverability=True)
    assert r.status is Check.UNKNOWN
    assert "unavailable" in r.detail


# --- address ----------------------------------------------------------------

def test_incomplete_address_is_unknown():
    r = V.verify_address(lead(city="Austin", state="TX"))  # no street, no zip
    assert r.status is Check.UNKNOWN
    assert "missing" in r.detail


def test_complete_address_is_unknown_not_pass():
    """Present is not USPS-valid; a complete-looking address still needs a CASS check."""
    r = V.verify_address(lead(address1="123 Congress Ave", city="Austin", state="TX", postal_code="78701"))
    assert r.status is Check.UNKNOWN
    assert "not confirmed against USPS" in r.detail


# --- grading ----------------------------------------------------------------

def test_grade_f_only_when_no_channel_is_usable():
    dq = verify_lead(lead(phone="5125551234567", email="not-an-email"), check_deliverability=False)
    assert dq.grade() == "F"
    assert dq.has_verified_channel is False
    assert dq.has_blocking_defect is True


def test_grade_b_with_one_verified_channel():
    dq = verify_lead(lead(phone="5125550147", email="not-an-email"), check_deliverability=False)
    assert dq.grade() == "B"
    assert dq.has_verified_channel is True


def test_verified_channel_requires_a_pass_not_an_unknown():
    """A lead with only unverifiable contact info has no *verified* channel."""
    dq = verify_lead(lead(phone=None, email="pat@example.com"), check_deliverability=False)
    assert dq.has_verified_channel is False  # email is UNKNOWN, phone missing
