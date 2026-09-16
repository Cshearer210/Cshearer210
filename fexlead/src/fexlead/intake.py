"""Vendor-agnostic lead intake.

Final expense vendors deliver in three shapes: a real-time HTTP POST, a CSV drop,
or a CRM push. The field names differ per vendor and change without notice. This
module normalizes all of them into one Lead.

One rule: a source field that could not be mapped is reported, never dropped
silently. A vendor quietly renaming `trustedform_cert_url` to `tf_url` must
surface as an unmapped field, not as a lead that has silently stopped carrying
consent evidence.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Optional

from .schema import Consent, DNCStatus, Lead, LeadType, SelfReported

# Canonical field -> candidate source keys, matched case- and separator-insensitively.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "vendor_lead_id": ("lead_id", "id", "leadid", "vendor_lead_id", "reference"),
    "first_name": ("first_name", "fname", "firstname", "first"),
    "last_name": ("last_name", "lname", "lastname", "last", "surname"),
    "phone": ("phone", "phone1", "phone_number", "primary_phone", "home_phone", "cell"),
    "email": ("email", "email_address", "emailaddr"),
    "address1": ("address", "address1", "street", "street_address", "addr1"),
    "city": ("city", "town"),
    "state": ("state", "st", "state_code", "region"),
    "postal_code": ("zip", "zipcode", "zip_code", "postal", "postal_code"),
    "trustedform_url": ("trustedform_url", "trustedform_cert_url", "tf_url", "xxtrustedformcerturl", "cert_url"),
    "jornaya_leadid": ("jornaya_leadid", "leadid_token", "universal_leadid", "jornaya", "leadid"),
    "consent_timestamp": ("consent_timestamp", "opt_in_date", "optin_time", "consent_date", "tcpa_timestamp"),
    "consent_language": ("consent_language", "tcpa_language", "disclosure", "consent_text"),
    "source_url": ("source_url", "landing_page", "referrer", "origin_url"),
    "ip_address": ("ip_address", "ip", "user_ip", "consumer_ip"),
    "lead_created_at": ("created_at", "lead_date", "date_created", "submitted_at", "timestamp"),
    "age": ("age", "applicant_age"),
    "date_of_birth": ("dob", "date_of_birth", "birthdate"),
    "coverage_amount_requested": ("coverage_amount", "face_amount", "coverage", "requested_coverage"),
    "has_existing_coverage": ("existing_coverage", "has_coverage", "currently_insured"),
    "tobacco_use": ("tobacco", "smoker", "tobacco_use", "nicotine"),
    "beneficiary_relationship": ("beneficiary", "beneficiary_relationship", "bene_relationship"),
    "cost_cents": ("cost", "price", "lead_cost"),
    "shared_with_count": ("shared_with", "buyer_count", "sold_to_count", "num_buyers"),
}

TRUE_TOKENS = {"1", "true", "t", "yes", "y"}
FALSE_TOKENS = {"0", "false", "f", "no", "n"}


def _canon(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


_ALIAS_LOOKUP = {
    _canon(alias): canonical
    for canonical, aliases in FIELD_ALIASES.items()
    for alias in aliases
}


def _as_bool(v: Any) -> Optional[bool]:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in TRUE_TOKENS:
        return True
    if s in FALSE_TOKENS:
        return False
    return None


def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace("$", "").replace(",", "").strip())))
    except (TypeError, ValueError):
        return None


def _as_dt(v: Any) -> Optional[datetime]:
    """Parse a timestamp. Naive values are assumed UTC and marked as such.

    A vendor timestamp with no offset is genuinely ambiguous. Assuming UTC is a
    choice, and it is recorded in the parse warnings so it does not silently
    become a fact.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    for parse in (
        datetime.fromisoformat,
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%m/%d/%Y %H:%M"),
        lambda x: datetime.strptime(x, "%m/%d/%Y"),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
    ):
        try:
            dt = parse(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def normalize_phone(v: Any) -> Optional[str]:
    """Reduce to 10 digits. Anything that is not a plausible US number is dropped.

    Dropping is safe here only because a Lead with no phone fails the gate's
    suppression check as UNKNOWN rather than passing.
    """
    if not v:
        return None
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


@dataclass
class ParseResult:
    lead: Optional[Lead]
    unmapped_fields: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.lead is not None


def normalize_record(
    raw: dict[str, Any],
    vendor: str,
    lead_type: LeadType,
    lead_id: Optional[str] = None,
    received_at: Optional[datetime] = None,
) -> ParseResult:
    """Map one vendor record onto a Lead, reporting anything it could not place."""
    mapped: dict[str, Any] = {}
    unmapped: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in raw.items():
        canonical = _ALIAS_LOOKUP.get(_canon(key))
        if canonical is None:
            if value not in (None, ""):
                unmapped[key] = value
            continue
        mapped[canonical] = value

    phone = normalize_phone(mapped.get("phone"))
    if mapped.get("phone") and phone is None:
        warnings.append(f"phone {mapped['phone']!r} is not a valid 10-digit US number; dropped")

    consent_ts = _as_dt(mapped.get("consent_timestamp"))
    if mapped.get("consent_timestamp") and consent_ts is None:
        warnings.append(f"could not parse consent_timestamp {mapped['consent_timestamp']!r}")
    elif consent_ts and not str(mapped.get("consent_timestamp", "")).strip().endswith(("Z", "+00:00")):
        if isinstance(mapped.get("consent_timestamp"), str) and "+" not in str(mapped["consent_timestamp"]):
            warnings.append("consent_timestamp had no UTC offset; assumed UTC")

    created = _as_dt(mapped.get("lead_created_at"))
    if mapped.get("lead_created_at") and created is None:
        warnings.append(f"could not parse lead_created_at {mapped['lead_created_at']!r}")

    consent = Consent(
        trustedform_url=mapped.get("trustedform_url") or None,
        jornaya_leadid=mapped.get("jornaya_leadid") or None,
        consent_timestamp=consent_ts,
        consent_language=mapped.get("consent_language") or None,
        source_url=mapped.get("source_url") or None,
        ip_address=mapped.get("ip_address") or None,
        # Claim status is never inferred from a delivery payload. It is a fact
        # about your own retention, established by the claiming call, so it stays
        # None here and the gate reports UNKNOWN until that call is made.
        cert_claimed=None,
    )

    self_reported = SelfReported(
        age=_as_int(mapped.get("age")),
        coverage_amount_requested=_as_int(mapped.get("coverage_amount_requested")),
        has_existing_coverage=_as_bool(mapped.get("has_existing_coverage")),
        tobacco_use=_as_bool(mapped.get("tobacco_use")),
        beneficiary_relationship=mapped.get("beneficiary_relationship") or None,
        optional_fields_completed=sum(
            1 for k in ("coverage_amount_requested", "beneficiary_relationship", "tobacco_use", "email")
            if mapped.get(k) not in (None, "")
        ),
    )

    state = (mapped.get("state") or "").strip().upper() or None
    if state and len(state) != 2:
        warnings.append(f"state {state!r} is not a 2-letter code; timezone resolution will return UNKNOWN")

    lead = Lead(
        lead_id=lead_id or str(mapped.get("vendor_lead_id") or f"{vendor}-{phone or 'nophone'}"),
        vendor=vendor,
        lead_type=lead_type,
        first_name=(mapped.get("first_name") or "").strip() or None,
        last_name=(mapped.get("last_name") or "").strip() or None,
        phone=phone,
        email=(mapped.get("email") or "").strip() or None,
        address1=(mapped.get("address1") or "").strip() or None,
        city=(mapped.get("city") or "").strip() or None,
        state=state,
        postal_code=(str(mapped.get("postal_code") or "").strip() or None),
        consent=consent,
        self_reported=self_reported,
        vendor_lead_id=str(mapped.get("vendor_lead_id")) if mapped.get("vendor_lead_id") else None,
        lead_created_at=created,
        received_at=received_at or datetime.now(timezone.utc),
        cost_cents=_as_int(mapped.get("cost_cents")),
        shared_with_count=_as_int(mapped.get("shared_with_count")),
        # Scrub status is never taken from a vendor's own claim. It is established
        # by your scrub, against your subscription, at a time you can prove.
        dnc_status=DNCStatus.NOT_SCRUBBED,
        dnc_checked_at=None,
        litigator_flag=None,
    )

    return ParseResult(lead=lead, unmapped_fields=unmapped, warnings=warnings)


def from_csv(path: str, vendor: str, lead_type: LeadType) -> Iterator[ParseResult]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            yield normalize_record(row, vendor=vendor, lead_type=lead_type)


def from_payloads(
    payloads: Iterable[dict[str, Any]], vendor: str, lead_type: LeadType
) -> Iterator[ParseResult]:
    """For real-time webhook delivery. One payload per POST body."""
    for p in payloads:
        yield normalize_record(p, vendor=vendor, lead_type=lead_type)
