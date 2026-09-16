"""Contact-data verification: the honest answer to "how do you know the info is accurate?"

You cannot guarantee accuracy on data scraped about a stranger. You can verify it
when the person entered it themselves and then you check each field against an
authoritative source. That is what this module does, and it is the reason the whole
pipeline is built around opt-in leads rather than scraped ones: a scraped record has
nothing to verify against, while an opt-in record carries a phone the person typed, an
email they control, and a consent certificate proving they typed it.

Three verifiers, one rule. A field that verifies is PASS. A field that is provably
bad (an unassigned phone, a malformed email) is BLOCK. A field we could not check
because the checking service was unreachable is UNKNOWN, never PASS. Accuracy you
could not confirm is not accuracy.

What this can and cannot promise, stated plainly:

- Phone: `phonenumbers` (Google's libphonenumber) confirms the number is a valid,
  assigned US number and reports its line type and area-code timezone. It cannot
  confirm the number currently belongs to this person -- that is what the DNC and
  Reassigned Numbers checks in the gate are for.
- Email: syntax is checked offline; deliverability (does the domain accept mail)
  is checked over DNS when reachable. Neither confirms the person reads that inbox.
- Address: completeness only. Real correctness needs a USPS CASS API, which is a
  paid adapter, so an address that looks complete is UNKNOWN-verified, not verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import phonenumbers
from phonenumbers import PhoneNumberType, number_type, timezone as pn_timezone
from email_validator import EmailNotValidError, validate_email

from .schema import Check, Lead

_LINE_TYPE_NAMES = {
    PhoneNumberType.FIXED_LINE: "landline",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "landline_or_mobile",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.UNKNOWN: "unknown",
}

# Line types that are implausible for a residential final expense prospect. Not a
# hard block on their own -- some consumers legitimately use VOIP -- but a signal
# that the record may be low quality or a lead-farm number.
SUSPECT_LINE_TYPES = {"toll_free", "premium_rate"}


@dataclass
class FieldResult:
    field_name: str
    status: Check
    detail: str
    extra: dict = field(default_factory=dict)

    @property
    def is_pass(self) -> bool:
        return self.status is Check.PASS


def verify_phone(phone: Optional[str], region: str = "US") -> FieldResult:
    if not phone:
        return FieldResult("phone", Check.UNKNOWN, "no phone number on the record")
    try:
        parsed = phonenumbers.parse(phone, region)
    except phonenumbers.NumberParseException as exc:
        return FieldResult("phone", Check.BLOCK, f"unparseable: {exc}")

    if not phonenumbers.is_valid_number(parsed):
        return FieldResult(
            "phone", Check.BLOCK,
            "not a valid, assigned US number (wrong length or unassigned exchange)",
        )

    line = _LINE_TYPE_NAMES.get(number_type(parsed), "unknown")
    tzs = pn_timezone.time_zones_for_number(parsed)
    tz = tzs[0] if tzs and tzs[0] != "Etc/Unknown" else None
    extra = {"line_type": line, "area_code_timezone": tz}

    if line in SUSPECT_LINE_TYPES:
        return FieldResult(
            "phone", Check.UNKNOWN,
            f"valid number but line type is {line}, which is unusual for a residential prospect",
            extra,
        )
    return FieldResult("phone", Check.PASS, f"valid US {line} number", extra)


def verify_email(email: Optional[str], check_deliverability: bool = True) -> FieldResult:
    if not email:
        return FieldResult("email", Check.UNKNOWN, "no email on the record")
    # Syntax first, always available offline.
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        return FieldResult("email", Check.BLOCK, f"invalid syntax: {exc}")

    if not check_deliverability:
        return FieldResult("email", Check.UNKNOWN, "syntax valid; deliverability not checked")

    # Deliverability needs DNS. If the lookup itself fails (no network, timeout),
    # that is UNKNOWN -- we could not check -- not a clean pass and not a failure.
    try:
        validate_email(email, check_deliverability=True)
    except EmailNotValidError as exc:
        return FieldResult("email", Check.BLOCK, f"domain does not accept mail: {exc}")
    except Exception as exc:  # noqa: BLE001 - DNS unreachable etc.
        return FieldResult("email", Check.UNKNOWN, f"deliverability check unavailable: {type(exc).__name__}")
    return FieldResult("email", Check.PASS, "valid syntax and domain accepts mail")


def verify_address(lead: Lead) -> FieldResult:
    """Completeness only. Real correctness requires a USPS CASS adapter (paid)."""
    parts = {
        "street": lead.address1,
        "city": lead.city,
        "state": lead.state,
        "zip": lead.postal_code,
    }
    missing = [name for name, val in parts.items() if not (val and str(val).strip())]
    if missing:
        return FieldResult("address", Check.UNKNOWN, f"incomplete, missing: {', '.join(missing)}")
    has_number = any(ch.isdigit() for ch in (lead.address1 or ""))
    if not has_number:
        return FieldResult("address", Check.UNKNOWN, "street line has no number; may be a partial address")
    # All components present, but present is not the same as USPS-valid.
    return FieldResult(
        "address", Check.UNKNOWN,
        "all components present; not confirmed against USPS (needs a CASS adapter to reach PASS)",
    )


@dataclass
class DataQuality:
    lead_id: str
    fields: list[FieldResult] = field(default_factory=list)

    def get(self, name: str) -> FieldResult:
        return next(f for f in self.fields if f.field_name == name)

    @property
    def has_verified_channel(self) -> bool:
        """True if at least one contact channel is confirmed good.

        This is the accuracy bar that actually matters for a call sheet: is there a
        way to reach this person that we have verified, not merely received.
        """
        return any(f.field_name in ("phone", "email") and f.is_pass for f in self.fields)

    @property
    def has_blocking_defect(self) -> bool:
        return any(f.status is Check.BLOCK for f in self.fields)

    def grade(self) -> str:
        """A/B/C/F, for a quick sort. Explained by the field details, never on its own."""
        phone = self.get("phone")
        email = self.get("email")
        if phone.status is Check.BLOCK and email.status is Check.BLOCK:
            return "F"  # no usable contact channel at all
        if phone.is_pass and email.is_pass:
            return "A"
        if phone.is_pass or email.is_pass:
            return "B"
        return "C"  # nothing confirmed bad, nothing confirmed good

    def summary(self) -> str:
        return "; ".join(f"{f.field_name}={f.status.value}" for f in self.fields)


def verify_lead(lead: Lead, check_deliverability: bool = True) -> DataQuality:
    return DataQuality(
        lead_id=lead.lead_id,
        fields=[
            verify_phone(lead.phone),
            verify_email(lead.email, check_deliverability=check_deliverability),
            verify_address(lead),
        ],
    )
