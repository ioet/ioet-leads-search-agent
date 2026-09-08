"""Company careers-page job posting source."""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

import requests

from services.common.schemas import Company, JobPosting
from services.jobs.sources.base import JobPostingSource

logger = logging.getLogger(__name__)

CAREERS_PATHS = (
    "/careers",
    "/jobs",
    "/careers/jobs",
    "/about/careers",
    "/company/careers",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class CompanyWebsiteJobPostingSource(JobPostingSource):
    """Scrape public careers pages on the company domain."""

    source_id = "company_website"

    def __init__(self, session: requests.Session | None = None, timeout_seconds: int = 20) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def search(self, company: Company, *, max_results: int = 10) -> list[JobPosting]:
        if not company.domain:
            logger.info("Company website source skipped — no domain on %s", company.name)
            return []

        postings: list[JobPosting] = []
        for path in CAREERS_PATHS:
            url = f"https://{company.domain}{path}"
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "ioet-leads-agent/0.1 (+job-discovery)"},
                )
            except requests.RequestException as exc:
                logger.debug("Careers fetch failed for %s: %s", url, exc)
                continue
            if not response.ok:
                continue

            text = _html_to_text(response.text)
            if len(text) < 200:
                continue

            extracted = self._extract_postings(text, company, url, max_results=max_results)
            postings.extend(extracted)
            if len(postings) >= max_results:
                break

        return postings[:max_results]

    def _extract_postings(
        self,
        page_text: str,
        company: Company,
        page_url: str,
        *,
        max_results: int,
    ) -> list[JobPosting]:
        """Heuristic split of careers page text into posting-sized chunks."""
        chunks = _split_job_sections(page_text)
        postings: list[JobPosting] = []
        for idx, chunk in enumerate(chunks[:max_results]):
            title = _guess_title(chunk) or f"Open role at {company.name}"
            postings.append(
                JobPosting(
                    title=title,
                    source=self.source_id,
                    description=chunk[:8000],
                    url=page_url,
                )
            )
        if not postings and len(page_text) >= 200:
            postings.append(
                JobPosting(
                    title=f"Careers — {company.name}",
                    source=self.source_id,
                    description=page_text[:8000],
                    url=page_url,
                )
            )
        return postings


def _html_to_text(html: str) -> str:
    text = unescape(_TAG_RE.sub(" ", html))
    return _WS_RE.sub(" ", text).strip()


def _split_job_sections(text: str) -> list[str]:
    """Split on common job-title patterns; fall back to paragraph windows."""
    pattern = re.compile(
        r"(?:^|\n)\s*("
        r"(?:Senior\s+)?(?:Staff\s+)?(?:Principal\s+)?"
        r"(?:Software\s+)?(?:Engineer|Developer|Architect|Manager|Designer|Analyst|SRE|DevOps)"
        r"[^.\n]{0,80})",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return [text[:8000]] if text else []

    sections: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if len(section) >= 120:
            sections.append(section[:8000])
    return sections


def _guess_title(chunk: str) -> str | None:
    first_line = chunk.split(".", 1)[0].strip()
    if 8 <= len(first_line) <= 120:
        return first_line
    return None
