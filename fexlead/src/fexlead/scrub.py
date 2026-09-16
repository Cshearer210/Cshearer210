"""Scrub adapters: the concrete layer that fills a lead's compliance fields.

The gate only reads compliance state off a Lead. This module is what puts it
there. It defines provider-agnostic adapter interfaces, ships in-memory
implementations so the whole pipeline runs end to end without a paid account, and
provides a batch runner that applies every configured adapter to a batch of leads
and records exactly what ran.

The rule that governs every adapter: a lookup that could not complete must raise,
never return a clean-looking default. The batch runner catches the raise and
leaves that field in its NOT_SCRUBBED / NOT_QUERIED / None state, which the gate
reads as UNKNOWN. A provider outage must degrade to "we do not know", never to
"everyone is clear". This is the same failure this whole package is built to
prevent, pushed down to the integration boundary where real outages happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol

from .schema import DNCStatus, Lead, ReassignedStatus


class DNCAdapter(Protocol):
    """Returns the DNC registry status for a 10-digit number, or raises.

    A real implementation wraps a scrub provider (Blacklist Alliance, PossibleNOW,
    DNC.com) or the FTC registry download. It must raise on any failure to reach
    the provider rather than returning CLEAR.
    """

    def status(self, phone: str) -> DNCStatus: ...


class LitigatorAdapter(Protocol):
    """True if the number belongs to a known TCPA serial plaintiff, or raises."""

    def is_litigator(self, phone: str) -> bool: ...


class ReassignedAdapter(Protocol):
    """FCC Reassigned Numbers Database lookup for a number as of the consent date.

    The consent date is required, not optional: the database answers the specific
    question "was this number reassigned between the consent date and now", and a
    query without a date cannot claim the safe harbor.
    """

    def status(self, phone: str, consent_date: datetime) -> ReassignedStatus: ...


# --- in-memory reference implementations -------------------------------------
# These make the pipeline runnable and testable. They are not scrub services and
# must never be presented as one. A number not listed is treated as clear by the
# DNC mock only because the mock is authoritative over its own fixture; a real
# adapter has no such luxury and must query.


@dataclass
class InMemoryDNC:
    on_dnc: set[str] = field(default_factory=set)
    unreachable: set[str] = field(default_factory=set)  # simulate provider outage

    def status(self, phone: str) -> DNCStatus:
        if phone in self.unreachable:
            raise ConnectionError(f"DNC provider timeout for {phone}")
        return DNCStatus.ON_FEDERAL_DNC if phone in self.on_dnc else DNCStatus.CLEAR


@dataclass
class InMemoryLitigator:
    litigators: set[str] = field(default_factory=set)
    unreachable: set[str] = field(default_factory=set)

    def is_litigator(self, phone: str) -> bool:
        if phone in self.unreachable:
            raise ConnectionError(f"litigator DB timeout for {phone}")
        return phone in self.litigators


@dataclass
class InMemoryReassigned:
    reassigned: set[str] = field(default_factory=set)
    no_data: set[str] = field(default_factory=set)
    unreachable: set[str] = field(default_factory=set)

    def status(self, phone: str, consent_date: datetime) -> ReassignedStatus:
        if phone in self.unreachable:
            raise ConnectionError(f"RND timeout for {phone}")
        if phone in self.reassigned:
            return ReassignedStatus.REASSIGNED
        if phone in self.no_data:
            return ReassignedStatus.NO_DATA
        return ReassignedStatus.SAME_SUBSCRIBER


@dataclass
class ScrubReport:
    """What actually happened when a batch was scrubbed.

    Every count here is separate on purpose. "37 numbers scrubbed clean" and
    "37 numbers we failed to reach" must never collapse into one number, because
    the whole point is that a failed scrub is not a clean scrub.
    """

    total: int = 0
    dnc_checked: int = 0
    dnc_failed: int = 0
    litigator_checked: int = 0
    litigator_failed: int = 0
    reassigned_checked: int = 0
    reassigned_failed: int = 0
    skipped_no_phone: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.total} leads: "
            f"DNC {self.dnc_checked} ok / {self.dnc_failed} failed, "
            f"litigator {self.litigator_checked} ok / {self.litigator_failed} failed, "
            f"reassigned {self.reassigned_checked} ok / {self.reassigned_failed} failed, "
            f"{self.skipped_no_phone} skipped (no phone)"
        )


@dataclass
class ScrubRunner:
    """Applies configured adapters to leads, mutating their compliance fields.

    Any adapter may be None, in which case that dimension is left untouched and
    the gate reports it as UNKNOWN. This is deliberate: running the pipeline with
    no reassigned adapter yet configured should hold those leads, not wave them
    through.
    """

    dnc: Optional[DNCAdapter] = None
    litigator: Optional[LitigatorAdapter] = None
    reassigned: Optional[ReassignedAdapter] = None

    def scrub(self, leads: Iterable[Lead], now: Optional[datetime] = None) -> ScrubReport:
        now = now or datetime.now(timezone.utc)
        report = ScrubReport()

        for lead in leads:
            report.total += 1
            if not lead.phone:
                report.skipped_no_phone += 1
                continue

            if self.dnc is not None:
                try:
                    lead.dnc_status = self.dnc.status(lead.phone)
                    lead.dnc_checked_at = now
                    report.dnc_checked += 1
                except Exception as exc:  # noqa: BLE001 - failure leaves NOT_SCRUBBED
                    report.dnc_failed += 1
                    report.failures.append(f"dnc {lead.lead_id}: {exc}")

            if self.litigator is not None:
                try:
                    lead.litigator_flag = self.litigator.is_litigator(lead.phone)
                    report.litigator_checked += 1
                except Exception as exc:  # noqa: BLE001 - failure leaves None
                    report.litigator_failed += 1
                    report.failures.append(f"litigator {lead.lead_id}: {exc}")

            if self.reassigned is not None:
                consent_date = lead.consent.consent_timestamp
                if consent_date is None:
                    # No consent date means the RND query cannot be framed, so the
                    # field stays NOT_QUERIED and the gate holds the lead.
                    report.reassigned_failed += 1
                    report.failures.append(f"reassigned {lead.lead_id}: no consent date to query against")
                else:
                    try:
                        lead.reassigned_status = self.reassigned.status(lead.phone, consent_date)
                        lead.reassigned_checked_at = now
                        report.reassigned_checked += 1
                    except Exception as exc:  # noqa: BLE001 - failure leaves NOT_QUERIED
                        report.reassigned_failed += 1
                        report.failures.append(f"reassigned {lead.lead_id}: {exc}")

        return report
