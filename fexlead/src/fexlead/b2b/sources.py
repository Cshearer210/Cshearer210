"""B2B data sources: pluggable adapters over public business data.

Each source implements fetch(criteria) -> list[Company]. The legal posture that
governs all of them:

  - Public data only. No logged-in scraping, no defeating a technical barrier, no
    fake accounts. hiQ v. LinkedIn settled with a permanent injunction and a
    $500k payment precisely because scraping a logged-in/ToS-protected surface is
    a contract breach even when it is not a CFAA violation. Prefer official APIs
    and open-data feeds (SEC EDGAR, state Socrata portals, the Google Places API)
    over scraping HTML you were not invited to take.
  - Rate limits and robots.txt are honored, not worked around.
  - A named person's contact detail is personal data (CCPA covers B2B since 2023),
    so contacts carry provenance and this module never guesses an email and passes
    it off as found.

EdgarFormDSource talks to SEC EDGAR's real endpoints and therefore needs network
access; it will run wherever you deploy this, not inside a locked-down sandbox. The
in-memory source makes the whole pipeline testable without a network.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol

from .schema import BizContact, Company, SourceType


@dataclass
class ScrapeCriteria:
    """What a buyer selects in the dashboard before clicking Fetch."""

    count: int = 100
    states: Optional[list[str]] = None          # filter to these 2-letter states
    industries: Optional[list[str]] = None      # substring match on industry/SIC desc
    min_signal_date: Optional[datetime] = None  # only leads with a signal since then
    require_contact_channel: bool = False       # drop companies with no reachable line

    def matches(self, company: Company) -> bool:
        if self.states and (company.state or "").upper() not in {s.upper() for s in self.states}:
            return False
        if self.industries:
            hay = f"{company.industry or ''} {company.sic_code or ''}".lower()
            if not any(term.lower() in hay for term in self.industries):
                return False
        if self.min_signal_date and (company.signal_date is None or company.signal_date < self.min_signal_date):
            return False
        if self.require_contact_channel and not company.has_contact_channel():
            return False
        return True


class B2BSource(Protocol):
    name: str

    def fetch(self, criteria: ScrapeCriteria) -> list[Company]: ...


@dataclass
class InMemorySource:
    """A fixed set of companies, for tests and demos. Not a data service."""

    name: str = "in_memory"
    companies: list[Company] = field(default_factory=list)

    def fetch(self, criteria: ScrapeCriteria) -> list[Company]:
        return [c for c in self.companies if criteria.matches(c)][: criteria.count]


# SEC's fair-access policy requires a descriptive User-Agent with a real contact.
# Put your own company and email here before running against EDGAR.
SEC_USER_AGENT = "fexlead-b2b (set-your-real-contact@example.com)"
SEC_RATE_DELAY_SECONDS = 0.15  # stay well under SEC's ~10 req/s ceiling


@dataclass
class EdgarFormDSource:
    """Newly-funded private companies from SEC Form D filings.

    A Form D is filed when a company raises private capital. It names the issuer,
    its address and industry, and its executives/promoters -- and 'just raised
    money' is one of the warmest B2B signals there is. All of it is federal public
    record, retrieved through SEC's own JSON API, so there is no ToS to breach.

    Requires network access. In a sandbox with blocked egress this raises, which the
    ScrapeJob records as a source failure rather than silently returning nothing.
    """

    name: str = "sec_edgar_form_d"
    user_agent: str = SEC_USER_AGENT

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                    "Accept-Encoding": "gzip, deflate"})
        time.sleep(SEC_RATE_DELAY_SECONDS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
        return data

    def fetch(self, criteria: ScrapeCriteria) -> list[Company]:
        # EDGAR full-text search for recent Form D filings.
        # Real endpoint contract: https://efts.sec.gov/LATEST/search-index?q=&forms=D
        url = "https://efts.sec.gov/LATEST/search-index?q=%22%22&forms=D&dateRange=custom"
        raw = self._get(url)
        payload = json.loads(raw)
        hits = payload.get("hits", {}).get("hits", [])
        companies: list[Company] = []
        for hit in hits:
            src = hit.get("_source", {})
            cik = (src.get("cik") or [None])[0] if isinstance(src.get("cik"), list) else src.get("cik")
            company = self._company_from_submission(cik) if cik else None
            if company and criteria.matches(company):
                companies.append(company)
            if len(companies) >= criteria.count:
                break
        return companies

    def _company_from_submission(self, cik: str) -> Optional[Company]:
        cik10 = str(cik).zfill(10)
        raw = self._get(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        d = json.loads(raw)
        addr = (d.get("addresses") or {}).get("business", {})
        return Company(
            name=d.get("name", "").title(),
            source=SourceType.SEC_EDGAR,
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik10}",
            discovered_at=datetime.now(timezone.utc),
            industry=d.get("sicDescription"),
            sic_code=d.get("sic"),
            phone=addr.get("phone") or d.get("phone"),
            address1=addr.get("street1"),
            city=addr.get("city"),
            state=addr.get("stateOrCountry"),
            postal_code=addr.get("zipCode"),
            signal="Filed SEC Form D (private capital raise)",
            signal_date=datetime.now(timezone.utc),
            extra={"cik": cik10},
        )


@dataclass
class SourceRunReport:
    fetched: int = 0
    after_dedup: int = 0
    source_failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.fetched} fetched, {self.after_dedup} after dedup, "
                f"{len(self.source_failures)} source failures")


def run_sources(
    sources: Iterable[B2BSource], criteria: ScrapeCriteria
) -> tuple[list[Company], SourceRunReport]:
    """Fetch from every source, dedupe across them, record failures.

    A source that raises (network down, endpoint moved, rate-limited) is recorded as
    a failure and skipped. It never silently degrades the run to 'no results found'.
    """
    report = SourceRunReport()
    seen: dict[str, Company] = {}
    for source in sources:
        try:
            fetched = source.fetch(criteria)
        except Exception as exc:  # noqa: BLE001 - a failed source is reported, not hidden
            report.source_failures.append(f"{getattr(source, 'name', 'source')}: {exc}")
            continue
        report.fetched += len(fetched)
        for company in fetched:
            key = company.dedupe_key()
            if key not in seen:
                seen[key] = company
    result = list(seen.values())[: criteria.count]
    report.after_dedup = len(result)
    return result, report
