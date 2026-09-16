"""Synthetic lead generator, for exercising the pipeline.

Everything produced here is fabricated. Phone numbers are drawn from the
555-0100 through 555-0199 range reserved for fiction, emails use example.com,
and street addresses are placeholders. No record here corresponds to a real
person, and this module exists to test the schema end to end -- it is not a lead
source and must never be presented as one.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .schema import Consent, DNCStatus, Lead, LeadType, SelfReported

FIRST = ["Alex", "Bobbie", "Casey", "Dana", "Ellis", "Frankie", "Gale", "Harper",
         "Indy", "Jamie", "Kerry", "Lee", "Morgan", "Noel", "Quinn", "Reese",
         "Sam", "Tatum", "Val", "Wren"]
LAST = ["Alvarez", "Boone", "Castellano", "Delgado", "Ellsworth", "Fairbanks",
        "Guerrero", "Hollings", "Ivers", "Jessup", "Kowalski", "Lindqvist",
        "Mbeki", "Nakamura", "Okonkwo", "Pemberton", "Quintero", "Rasmussen",
        "Sundqvist", "Thibodeaux"]

# (state, zip, city, area_code). Mixed timezones on purpose, including states the
# resolver deliberately refuses to guess. Area codes match the city so the
# synthetic records are at least internally consistent.
PLACES = [
    ("TX", "78701", "Austin", "512"), ("TX", "79901", "El Paso", "915"),
    ("FL", "33101", "Miami", "305"), ("FL", "32501", "Pensacola", "850"),
    ("TN", "37201", "Nashville", "615"), ("TN", "37902", "Knoxville", "865"),
    ("KY", "40201", "Louisville", "502"), ("IN", "46201", "Indianapolis", "317"),
    ("CA", "90210", "Beverly Hills", "310"), ("OH", "43201", "Columbus", "614"),
    ("GA", "30301", "Atlanta", "404"), ("AZ", "85001", "Phoenix", "602"),
    ("OK", "73101", "Oklahoma City", "405"), ("MD", "21201", "Baltimore", "410"),
    ("NC", "27601", "Raleigh", "919"), ("MO", "63101", "St. Louis", "314"),
]

TYPE_WEIGHTS = [
    (LeadType.AGED, 0.45), (LeadType.SHARED_WEB, 0.20), (LeadType.EXCLUSIVE_WEB, 0.15),
    (LeadType.DIRECT_MAIL, 0.10), (LeadType.LIVE_TRANSFER, 0.05), (LeadType.TELEMARKETED, 0.05),
]
TYPE_COST_CENTS = {
    LeadType.AGED: (150, 900), LeadType.SHARED_WEB: (1200, 2200),
    LeadType.EXCLUSIVE_WEB: (2500, 5500), LeadType.DIRECT_MAIL: (3500, 5000),
    LeadType.LIVE_TRANSFER: (8000, 13000), LeadType.TELEMARKETED: (1500, 2800),
}


def generate(n: int = 100, seed: int = 20260916, now: datetime | None = None) -> list[Lead]:
    """Generate n synthetic leads with a realistic spread of compliance states."""
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    types, weights = zip(*TYPE_WEIGHTS)
    leads: list[Lead] = []

    for i in range(n):
        lt = rng.choices(types, weights=weights, k=1)[0]
        state, zipc, city, area = rng.choice(PLACES)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        lo, hi = TYPE_COST_CENTS[lt]

        age_days = rng.choice([2, 9, 21, 45, 75, 110, 200, 320]) if lt is LeadType.AGED else rng.uniform(0, 2)
        created = now - timedelta(days=age_days)

        # Consent completeness varies by vendor quality, which is the realistic case.
        tier = rng.random()
        if tier < 0.62:      # complete and claimed
            consent = Consent(
                trustedform_url=f"https://cert.trustedform.com/{rng.getrandbits(48):012x}",
                consent_timestamp=created,
                consent_language="By submitting I agree to be contacted about final expense coverage.",
                source_url="https://example.com/final-expense-quote",
                cert_claimed=True,
            )
        elif tier < 0.80:    # certificate present, never claimed
            consent = Consent(
                trustedform_url=f"https://cert.trustedform.com/{rng.getrandbits(48):012x}",
                consent_timestamp=created,
                consent_language="By submitting I agree to be contacted about final expense coverage.",
                cert_claimed=None,
            )
        elif tier < 0.92:    # Jornaya only, no language captured
            consent = Consent(
                jornaya_leadid=f"{rng.getrandbits(64):016X}",
                consent_timestamp=created,
                cert_claimed=True,
            )
        else:                # nothing usable
            consent = Consent()

        scrub = rng.random()
        if scrub < 0.70:
            dnc_status, checked = DNCStatus.CLEAR, now - timedelta(days=rng.uniform(0, 20))
        elif scrub < 0.80:
            dnc_status, checked = DNCStatus.CLEAR, now - timedelta(days=rng.uniform(35, 90))  # stale
        elif scrub < 0.90:
            dnc_status, checked = DNCStatus.ON_FEDERAL_DNC, now - timedelta(days=rng.uniform(0, 10))
        else:
            dnc_status, checked = DNCStatus.NOT_SCRUBBED, None

        leads.append(Lead(
            lead_id=f"SYN-{i:04d}",
            vendor=rng.choice(["vendor-alpha", "vendor-bravo", "vendor-charlie"]),
            lead_type=lt,
            first_name=first,
            last_name=last,
            phone=f"{area}555{rng.randint(100, 199):04d}",
            email=f"{first.lower()}.{last.lower()}@example.com" if rng.random() < 0.7 else None,
            address1=f"{rng.randint(100, 9999)} Placeholder {rng.choice(['St', 'Ave', 'Rd'])}",
            city=city,
            state=state,
            postal_code=zipc,
            consent=consent,
            self_reported=SelfReported(
                age=rng.randint(52, 84),
                coverage_amount_requested=rng.choice([None, 5000, 10000, 15000, 20000, 25000]),
                has_existing_coverage=rng.choice([None, True, False]),
                tobacco_use=rng.choice([None, True, False]),
                beneficiary_relationship=rng.choice([None, "spouse", "child", "grandchild"]),
                optional_fields_completed=rng.randint(0, 4),
            ),
            lead_created_at=created,
            received_at=now,
            dnc_status=dnc_status,
            dnc_checked_at=checked,
            cost_cents=rng.randint(lo, hi),
            shared_with_count=1 if lt is LeadType.EXCLUSIVE_WEB else rng.choice([1, 2, 3, 4, 5]),
            litigator_flag=None if rng.random() < 0.15 else (rng.random() < 0.02),
        ))
    return leads
