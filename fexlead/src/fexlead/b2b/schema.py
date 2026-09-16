"""B2B lead shapes. Business data, which the law treats very differently from PII.

A company's name, address, main line, and website are public business facts. A named
person's work email or cell is still 'personal information' under CCPA (the B2B
exemption expired January 2023), so contacts carry a provenance field: where the
datum came from, so a buyer can tell a published business fact from an appended
personal one. The distinction drives what a downstream buyer may legally do with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    SEC_EDGAR = "sec_edgar"                 # federal public record, cleanest
    STATE_REGISTRY = "state_registry"       # secretary-of-state open data
    MUNICIPAL_LICENSE = "municipal_license"
    LICENSING_BOARD = "licensing_board"
    MAPS_PLACES = "maps_places"             # via official Places API, not scraping
    MANUAL = "manual"
    MOCK = "mock"


@dataclass
class BizContact:
    """A person at a company. Personal data even in a business context."""

    full_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # Where each personal datum came from. "public_filing" (a named exec in an SEC
    # filing) is defensible; "inferred_pattern" (guessed first.last@domain) is not,
    # and a buyer must know which they are getting.
    provenance: str = "unknown"


@dataclass
class Company:
    """A business. The public-facts core of a B2B lead."""

    name: str
    source: SourceType
    source_url: Optional[str] = None
    discovered_at: Optional[datetime] = None

    domain: Optional[str] = None
    industry: Optional[str] = None
    sic_code: Optional[str] = None
    phone: Optional[str] = None
    address1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    employee_count: Optional[int] = None

    # A B2B "intent" signal: something that happened recently making this a warm
    # lead (a funding raise, a new registration, a new license). Free-text plus a
    # date so scoring can weight recency.
    signal: Optional[str] = None
    signal_date: Optional[datetime] = None

    contacts: list[BizContact] = field(default_factory=list)
    # Firmographic extras keyed by name, so a source can attach fields the schema
    # does not model without losing them.
    extra: dict = field(default_factory=dict)

    def dedupe_key(self) -> str:
        """Identity for de-duplication across sources. Domain first, then name+state."""
        if self.domain:
            return f"domain:{self.domain.lower().strip()}"
        return f"name:{self.name.lower().strip()}|{(self.state or '').upper()}"

    def has_contact_channel(self) -> bool:
        if self.phone:
            return True
        return any(c.email or c.phone for c in self.contacts)
