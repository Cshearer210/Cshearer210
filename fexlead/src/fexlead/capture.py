"""Lead capture: turn a first-party opt-in form submission into a sellable lead.

This is the front of the funnel and the whole reason the leads coming out of it are
worth money. A sellable final expense lead is not a name and a phone number. It is a
person who filled out your form, plus the machine-readable proof that they did so:
a consent certificate token, the exact consent language they saw, a timestamp, and
their IP. Agents pay for that proof, because it is their TCPA defense.

Because this is a first-party form -- you own the page, you own the consent capture --
you can claim the TrustedForm certificate server-side the moment the lead arrives, so
these leads are born with cert_claimed=True rather than the None that haunts purchased
aged leads. That single difference is why self-generated inventory is worth more than
anything you can buy.

What this module refuses to do: fabricate any of it. Every consent field must come
from the actual submission. A capture with no certificate token and no consent text is
not downgraded to "probably fine" -- it produces a lead the gate will hold, because a
lead you cannot prove consent for is not sellable and not callable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .intake import normalize_phone
from .schema import Consent, DNCStatus, Lead, LeadType, ReassignedStatus, SelfReported

# The consent language your form must display, verbatim, near the submit button.
# This is prior express written consent under the TCPA. Keep "consent is not a
# condition of purchase" -- conditioning a sale on consent voids it. This is a
# template; have counsel confirm the partner-disclosure wording for your setup.
STANDARD_CONSENT_TEMPLATE = (
    "By clicking Submit, I give my prior express written consent to be contacted by "
    "{company} and the licensed insurance agents it works with at the phone number and "
    "email I provided, about final expense and life insurance, including by autodialer, "
    "prerecorded or artificial voice, and text message. Consent is not a condition of "
    "purchase. Message and data rates may apply. I can opt out at any time."
)


@dataclass
class CaptureResult:
    lead: Optional[Lead]
    sellable: bool
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return self.lead is not None


def lead_from_capture(
    form: dict[str, Any],
    *,
    company: str,
    consent_language_shown: str,
    trustedform_token: Optional[str] = None,
    jornaya_token: Optional[str] = None,
    source_url: Optional[str] = None,
    ip_address: Optional[str] = None,
    lead_id: Optional[str] = None,
    now: Optional[datetime] = None,
    cert_claimed: Optional[bool] = None,
) -> CaptureResult:
    """Build a first-party opt-in Lead from a landing-page form submission.

    trustedform_token / jornaya_token come from the hidden fields the vendor scripts
    populate on your page. consent_language_shown must be the exact text the consumer
    saw -- not the template, the rendered string with {company} filled in -- because
    that is what you may one day have to produce in a dispute.

    cert_claimed defaults to None (unknown). Pass True only after your server has
    actually called the TrustedForm claim API for this certificate; claiming is what
    keeps it from being deleted at 72 hours. Do not pass True to mean "we intend to".
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    phone = normalize_phone(form.get("phone"))
    if form.get("phone") and phone is None:
        reasons.append(f"phone {form.get('phone')!r} is not a valid US number")

    has_cert = bool(trustedform_token or jornaya_token)
    if not has_cert:
        reasons.append("no consent certificate token captured; lead is not sellable")
    if not consent_language_shown or not consent_language_shown.strip():
        reasons.append("no consent language recorded; lead is not sellable")

    consent = Consent(
        trustedform_url=trustedform_token or None,
        jornaya_leadid=jornaya_token or None,
        consent_timestamp=now if has_cert else None,
        consent_language=consent_language_shown or None,
        source_url=source_url,
        ip_address=ip_address,
        cert_claimed=cert_claimed,
    )

    def _int(v: Any) -> Optional[int]:
        try:
            return int(str(v).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            return None

    age = _int(form.get("age"))

    self_reported = SelfReported(
        age=age,
        coverage_amount_requested=_int(form.get("coverage_amount")),
        has_existing_coverage=_bool(form.get("has_existing_coverage")),
        tobacco_use=_bool(form.get("tobacco_use")),
        beneficiary_relationship=(form.get("beneficiary_relationship") or "").strip() or None,
        optional_fields_completed=sum(
            1 for k in ("coverage_amount", "beneficiary_relationship", "tobacco_use", "email")
            if form.get(k) not in (None, "")
        ),
    )

    state = (form.get("state") or "").strip().upper() or None

    lead = Lead(
        lead_id=lead_id or f"{company.lower().replace(' ', '')}-{phone or 'nophone'}-{int(now.timestamp())}",
        vendor=company,                       # you are the vendor now
        lead_type=LeadType.EXCLUSIVE_WEB,     # first-party, sold to one buyer = exclusive
        first_name=(form.get("first_name") or "").strip() or None,
        last_name=(form.get("last_name") or "").strip() or None,
        phone=phone,
        email=(form.get("email") or "").strip() or None,
        address1=(form.get("address1") or "").strip() or None,
        city=(form.get("city") or "").strip() or None,
        state=state,
        postal_code=(str(form.get("postal_code") or "").strip() or None),
        consent=consent,
        self_reported=self_reported,
        lead_created_at=now,
        received_at=now,
        shared_with_count=1,                  # exclusive by construction
        # Scrub state is never assumed at capture; the pipeline scrubs before sale.
        dnc_status=DNCStatus.NOT_SCRUBBED,
        reassigned_status=ReassignedStatus.NOT_QUERIED,
    )

    if age is not None and age < 50:
        reasons.append(f"applicant age {age} is under the 50+ target; still captured, flag for routing")

    sellable = has_cert and bool(consent_language_shown and consent_language_shown.strip()) and phone is not None
    return CaptureResult(lead=lead, sellable=sellable, reasons=reasons)


def _bool(v: Any) -> Optional[bool]:
    if v in (None, ""):
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return None
