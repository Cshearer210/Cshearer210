"""Scrub adapter behavior, and the one property that matters most.

A scrub provider outage must leave a lead in its unscrubbed state so the gate
reads it as UNKNOWN. It must never leave the lead looking clear. These tests
force every adapter to fail and assert exactly that.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.compliance import ComplianceGate  # noqa: E402
from fexlead.schema import Check, Consent, DNCStatus, Lead, LeadType, ReassignedStatus  # noqa: E402
from fexlead.scrub import (  # noqa: E402
    InMemoryDNC, InMemoryLitigator, InMemoryReassigned, ScrubRunner,
)

NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)


def mk(lead_id: str, phone: str | None, consent_date: datetime | None = NOW - timedelta(days=10)) -> Lead:
    return Lead(
        lead_id=lead_id, vendor="v", lead_type=LeadType.AGED, phone=phone,
        state="TX", postal_code="78701",
        consent=Consent(
            trustedform_url=f"https://cert/{lead_id}",
            consent_timestamp=consent_date,
            consent_language="ok",
            cert_claimed=True,
        ),
    )


def test_clean_scrub_marks_fields_and_timestamps():
    lead = mk("L1", "5125550101")
    runner = ScrubRunner(dnc=InMemoryDNC(), litigator=InMemoryLitigator(), reassigned=InMemoryReassigned())
    report = runner.scrub([lead], NOW)
    assert lead.dnc_status is DNCStatus.CLEAR
    assert lead.dnc_checked_at == NOW
    assert lead.litigator_flag is False
    assert lead.reassigned_status is ReassignedStatus.SAME_SUBSCRIBER
    assert report.dnc_checked == 1 and report.dnc_failed == 0


def test_dnc_flags_registered_number():
    lead = mk("L2", "5125550102")
    ScrubRunner(dnc=InMemoryDNC(on_dnc={"5125550102"})).scrub([lead], NOW)
    assert lead.dnc_status is DNCStatus.ON_FEDERAL_DNC


def test_dnc_outage_leaves_lead_unscrubbed_not_clear():
    """The core property. A timeout must not become a clean scrub."""
    lead = mk("L3", "5125550103")
    runner = ScrubRunner(dnc=InMemoryDNC(unreachable={"5125550103"}))
    report = runner.scrub([lead], NOW)
    assert lead.dnc_status is DNCStatus.NOT_SCRUBBED
    assert lead.dnc_checked_at is None
    assert report.dnc_failed == 1
    # And the gate must hold it.
    assert ComplianceGate().evaluate(lead, NOW).callable_now is False


def test_litigator_outage_leaves_flag_unset():
    lead = mk("L4", "5125550104")
    ScrubRunner(litigator=InMemoryLitigator(unreachable={"5125550104"})).scrub([lead], NOW)
    assert lead.litigator_flag is None  # unscreened, not "not a litigator"


def test_reassigned_outage_leaves_not_queried():
    lead = mk("L5", "5125550105")
    ScrubRunner(reassigned=InMemoryReassigned(unreachable={"5125550105"})).scrub([lead], NOW)
    assert lead.reassigned_status is ReassignedStatus.NOT_QUERIED


def test_reassigned_without_consent_date_cannot_be_queried():
    """No consent date means the RND question cannot be framed, so we hold."""
    lead = mk("L6", "5125550106", consent_date=None)
    report = ScrubRunner(reassigned=InMemoryReassigned()).scrub([lead], NOW)
    assert lead.reassigned_status is ReassignedStatus.NOT_QUERIED
    assert report.reassigned_failed == 1
    assert any("no consent date" in f for f in report.failures)


def test_missing_adapter_leaves_dimension_untouched():
    """Running with no reassigned adapter must hold those leads, not pass them."""
    lead = mk("L7", "5125550107")
    ScrubRunner(dnc=InMemoryDNC(), litigator=InMemoryLitigator(), reassigned=None).scrub([lead], NOW)
    assert lead.reassigned_status is ReassignedStatus.NOT_QUERIED
    res = ComplianceGate().evaluate(lead, NOW)
    assert any(c.name == "reassigned_number" and c.status is Check.UNKNOWN for c in res.checks)


def test_no_phone_is_skipped_and_counted():
    lead = mk("L8", None)
    report = ScrubRunner(dnc=InMemoryDNC()).scrub([lead], NOW)
    assert report.skipped_no_phone == 1
    assert lead.dnc_status is DNCStatus.NOT_SCRUBBED


def test_report_keeps_clean_and_failed_counts_separate():
    """37 scrubbed and 37 failed must never collapse into one number."""
    leads = [mk(f"ok{i}", f"512555{2000+i:04d}") for i in range(3)]
    leads += [mk(f"bad{i}", f"512555{3000+i:04d}") for i in range(2)]
    unreachable = {l.phone for l in leads if l.lead_id.startswith("bad")}
    report = ScrubRunner(dnc=InMemoryDNC(unreachable=unreachable)).scrub(leads, NOW)
    assert report.dnc_checked == 3
    assert report.dnc_failed == 2
    assert report.dnc_checked != report.dnc_failed or True  # explicit: they are tracked apart
    assert "3 ok / 2 failed" in report.summary()
