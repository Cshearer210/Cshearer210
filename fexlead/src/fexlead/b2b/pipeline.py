"""One call behind the dashboard's Fetch button: criteria -> sources -> dedupe -> Excel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from .export import write_xlsx
from .schema import Company
from .sources import B2BSource, ScrapeCriteria, SourceRunReport, run_sources


@dataclass
class ScrapeJobResult:
    companies: list[Company]
    report: SourceRunReport
    output_path: Optional[str] = None


def run_scrape_job(
    sources: Iterable[B2BSource],
    criteria: ScrapeCriteria,
    output_path: Optional[str] = None,
    now: Optional[datetime] = None,
    check_email_deliverability: bool = False,
) -> ScrapeJobResult:
    now = now or datetime.now(timezone.utc)
    companies, report = run_sources(sources, criteria)
    path = None
    if output_path:
        path = write_xlsx(companies, output_path, now=now,
                          check_email_deliverability=check_email_deliverability)
    return ScrapeJobResult(companies=companies, report=report, output_path=path)
