"""Every gate in this suite is made to fail on purpose.

A check that has never been observed returning BLOCK is not a check, and a check
that has never been observed returning UNKNOWN cannot be trusted to notice its
own data dependency going away. The final test in this file enforces both across
every check the gate runs, so adding a new check without failure coverage breaks
the build rather than quietly shipping an always-green gate.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.compliance import ComplianceGate, GateResult  # noqa: E402
from fexlead.schema import Check, Consent, DNCStatus, Lead, LeadType  # noqa: E402

NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)      # 12:00 CDT in Chicago
NOW_NIGHT = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)  # 23:00 CDT in Chicago
NOW_FL_EDGE = datetime(2026, 9, 17, 0, 30, tzinfo=timezone.utc)  # 20:30 EDT in Miami

# Every (check_name, status) pair this suite has actually observed.
OBSERVED: dict[str, set[Check]] = defaultdict(set)


def record(result: GateResult) -> GateResult:
    for c in result.checks:
        OBSERVED[c.name].add(c.status)
    return result


class StaticSuppression:
    def __init__(self, numbers: set[str]) -> None:
        self.numbers = numbers

    def contains(self, phone: str) -> bool:
        return phone in self.numbers


class BrokenSuppression:
    """Stands in for the suppression store being unreachable."""

    def contains(self, phone: str) -> bool:
        raise ConnectionError("suppression store timed out")


class StaticHistory:
    def __init__(self, count: int) -> None:
        self.count = count

    def calls_in_last_24h(self, phone: str, subject: str) -> int:
        return self.count


def clean_lead(**overrides) -> Lead:
    """A lead that passes every check, so each test can break exactly one thing."""
    lead = Lead(
        lead_id="clean-1",
        vendor="test-vendor",
        lead_type=LeadType.AGED,
        first_name="Pat",
        last_name="Rivera",
        phone="5125550147",
        state="TX",
        postal_code="78701",
        consent=Consent(
            trustedform_url="https://cert.trustedform.com/testcert",
            consent_timestamp=NOW - timedelta(days=20),
            consent_language="By clicking submit I agree to be contacted about final expense coverage.",
            cert_claimed=True,
        ),
        dnc_status=DNCStatus.CLEAR,
        dnc_checked_at=NOW - timedelta(days=2),
        litigator_flag=False,
    )
    for k, v in overrides.items():
        setattr(lead, k, v)
    return lead


def gate(**kw) -> ComplianceGate:
    kw.setdefault("suppression", StaticSuppression(set()))
    kw.setdefault("call_history", StaticHistory(0))
    return ComplianceGate(**kw)


def status_of(result: GateResult, name: str) -> Check:
    return next(c.status for c in result.checks if c.name == name)


# --- the baseline: the clean lead must actually pass -------------------------

def test_clean_lead_is_callable():
    res = record(gate().evaluate(clean_lead(), NOW))
    assert res.callable_now, res.summary()


# --- consent ----------------------------------------------------------------

def test_consent_unknown_without_certificate():
    res = record(gate().evaluate(clean_lead(consent=Consent()), NOW))
    assert status_of(res, "consent") is Check.UNKNOWN
    assert not res.callable_now


def test_consent_blocks_on_unclaimed_expired_certificate():
    c = Consent(
        trustedform_url="https://cert.trustedform.com/testcert",
        consent_timestamp=NOW - timedelta(days=20),
        consent_language="agreed",
        cert_claimed=False,
    )
    res = record(gate().evaluate(clean_lead(consent=c), NOW))
    assert status_of(res, "consent") is Check.BLOCK


def test_consent_unknown_when_claim_status_missing():
    c = Consent(
        trustedform_url="https://cert.trustedform.com/testcert",
        consent_timestamp=NOW - timedelta(days=20),
        consent_language="agreed",
        cert_claimed=None,
    )
    res = record(gate().evaluate(clean_lead(consent=c), NOW))
    assert status_of(res, "consent") is Check.UNKNOWN


# --- dnc --------------------------------------------------------------------

def test_dnc_unknown_when_never_scrubbed():
    res = record(gate().evaluate(
        clean_lead(dnc_status=DNCStatus.NOT_SCRUBBED, dnc_checked_at=None), NOW))
    assert status_of(res, "dnc") is Check.UNKNOWN


def test_dnc_unknown_when_scrub_is_stale():
    """A 45-day-old scrub is not a scrub; the TSR requires re-scrubbing every 31 days."""
    res = record(gate().evaluate(
        clean_lead(dnc_checked_at=NOW - timedelta(days=45)), NOW))
    assert status_of(res, "dnc") is Check.UNKNOWN


def test_dnc_blocks_registered_number():
    res = record(gate().evaluate(clean_lead(dnc_status=DNCStatus.ON_FEDERAL_DNC), NOW))
    assert status_of(res, "dnc") is Check.BLOCK


# --- internal suppression ---------------------------------------------------

def test_suppression_blocks_prior_opt_out():
    g = gate(suppression=StaticSuppression({"5125550147"}))
    res = record(g.evaluate(clean_lead(), NOW))
    assert status_of(res, "internal_suppression") is Check.BLOCK


def test_suppression_unknown_when_store_unreachable():
    """The original bug class: a data dependency fails and everything downstream passes."""
    g = gate(suppression=BrokenSuppression())
    res = record(g.evaluate(clean_lead(), NOW))
    assert status_of(res, "internal_suppression") is Check.UNKNOWN
    assert not res.callable_now


def test_suppression_unknown_when_not_configured():
    g = ComplianceGate(suppression=None, call_history=StaticHistory(0))
    res = record(g.evaluate(clean_lead(), NOW))
    assert status_of(res, "internal_suppression") is Check.UNKNOWN


# --- litigator --------------------------------------------------------------

def test_litigator_blocks_known_plaintiff():
    res = record(gate().evaluate(clean_lead(litigator_flag=True), NOW))
    assert status_of(res, "litigator") is Check.BLOCK


def test_litigator_unknown_when_unscreened():
    res = record(gate().evaluate(clean_lead(litigator_flag=None), NOW))
    assert status_of(res, "litigator") is Check.UNKNOWN


# --- calling window ---------------------------------------------------------

def test_calling_window_blocks_outside_hours():
    res = record(gate().evaluate(clean_lead(), NOW_NIGHT))
    assert status_of(res, "calling_window") is Check.BLOCK


def test_calling_window_unknown_when_timezone_unresolvable():
    """Kentucky spans two zones and is not modeled, so it must not be guessed."""
    res = record(gate().evaluate(clean_lead(state="KY", postal_code="40201"), NOW))
    assert status_of(res, "calling_window") is Check.UNKNOWN


def test_florida_window_is_stricter_than_federal():
    """20:30 local is legal federally but not in Florida."""
    fl = clean_lead(state="FL", postal_code="33101")
    res = record(gate().evaluate(fl, NOW_FL_EDGE))
    assert status_of(res, "calling_window") is Check.BLOCK

    tx = clean_lead(state="TX", postal_code="78701")
    tx_res = record(gate().evaluate(tx, NOW_FL_EDGE))
    assert status_of(tx_res, "calling_window") is Check.PASS


# --- state frequency cap ----------------------------------------------------

def test_frequency_cap_blocks_at_florida_limit():
    g = gate(call_history=StaticHistory(3))
    res = record(g.evaluate(clean_lead(state="FL", postal_code="33101"), NOW))
    assert status_of(res, "state_frequency_cap") is Check.BLOCK


def test_frequency_cap_unknown_without_history_source():
    g = ComplianceGate(suppression=StaticSuppression(set()), call_history=None)
    res = record(g.evaluate(clean_lead(state="FL", postal_code="33101"), NOW))
    assert status_of(res, "state_frequency_cap") is Check.UNKNOWN


# --- gate-level invariants --------------------------------------------------

def test_single_unknown_makes_lead_uncallable():
    """The whole point: one check that could not run sinks the lead."""
    res = record(gate().evaluate(clean_lead(litigator_flag=None), NOW))
    assert status_of(res, "litigator") is Check.UNKNOWN
    assert all(c.status is Check.PASS for c in res.checks if c.name != "litigator")
    assert not res.callable_now


def test_partition_drops_nothing():
    leads = [clean_lead(), clean_lead(dnc_status=DNCStatus.ON_FEDERAL_DNC), clean_lead(litigator_flag=None)]
    callable_leads, held = gate().partition(leads, NOW)
    assert len(callable_leads) + len(held) == len(leads)
    assert len(callable_leads) == 1


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        gate().evaluate(clean_lead(), datetime(2026, 9, 16, 12, 0))


def test_stale_consent_warns_without_blocking():
    old = Consent(
        trustedform_url="https://cert.trustedform.com/testcert",
        consent_timestamp=NOW - timedelta(days=400),
        consent_language="agreed",
        cert_claimed=True,
    )
    res = record(gate().evaluate(clean_lead(consent=old), NOW))
    assert res.callable_now
    assert any("consent is 400 days old" in w for w in res.warnings)


# --- the meta-test ----------------------------------------------------------

def test_every_check_has_been_made_to_fail():
    """Enforces the rule that gives this file its name.

    Runs last (alphabetically ordered fixtures aside, pytest runs in file order),
    and asserts that across the whole suite every check was observed returning
    PASS, BLOCK and UNKNOWN at least once. A new check added to the gate without
    failure coverage fails here instead of shipping as an always-green gate.
    """
    expected = {
        "consent", "dnc", "internal_suppression",
        "litigator", "calling_window", "state_frequency_cap",
    }
    missing_checks = expected - OBSERVED.keys()
    assert not missing_checks, f"checks never exercised at all: {sorted(missing_checks)}"

    incomplete = {
        name: sorted(s.value for s in ({Check.PASS, Check.BLOCK, Check.UNKNOWN} - statuses))
        for name, statuses in OBSERVED.items()
        if {Check.PASS, Check.BLOCK, Check.UNKNOWN} - statuses
    }
    assert not incomplete, (
        "these checks were never observed returning every status; "
        f"a check that cannot be made to fail is not a check: {incomplete}"
    )
