"""Company careers-page job posting source."""

from __future__ import annotations

import logging
import re
from html import unescape

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
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_JS_HINTS = (
    "function(",
    "function (",
    "!function",
    "window.",
    "document.",
    "=>{",
    "=> {",
    "googletagmanager",
    "rebamboodomains",
    "jquery",
    "webpackjsonp",
)
_JUNK_TITLE_RE = re.compile(
    r"[{}=;]|function\s*\(|=>|!window|</|<!--|^\s*(?:var|const|let|if)\b",
    re.IGNORECASE,
)


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
            if len(text) < 200 or _looks_like_code(text) or _looks_like_directory(text):
                logger.info("Skipping careers page that is not a job posting: %s", url)
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
        for chunk in chunks:
            if _looks_like_code(chunk):
                continue
            title = _guess_title(chunk)
            if not title or _is_junk_title(title):
                continue
            if _looks_like_directory(chunk):
                continue
            postings.append(
                JobPosting(
                    title=title,
                    source=self.source_id,
                    description=chunk[:4000],
                    url=page_url,
                )
            )
            if len(postings) >= max_results:
                break
        return postings


def _html_to_text(html: str) -> str:
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _COMMENT_RE.sub(" ", cleaned)
    text = unescape(_TAG_RE.sub(" ", cleaned))
    return _WS_RE.sub(" ", text).strip()


def _looks_like_code(text: str) -> bool:
    sample = text[:6000].lower()
    hits = sum(1 for hint in _JS_HINTS if hint in sample)
    if hits >= 2:
        return True
    return hits >= 1 and sample.count(";") >= 8


def _is_junk_title(title: str) -> bool:
    return bool(_JUNK_TITLE_RE.search(title.strip()))


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


_ROLE_TITLE_RE = re.compile(
    r"(?:Senior|Staff|Principal|Lead|Junior|Mid)?\s*"
    r"(?:Software|Backend|Frontend|Full[- ]Stack|Platform|Data|DevOps|QA|Product|Mobile|Cloud)?\s*"
    r"(?:Engineer|Developer|Architect|Designer|Manager|Analyst|SRE)",
    re.IGNORECASE,
)
_LOREM_RE = re.compile(r"\b(lorem|ipsum|vivamus|aenean|vestibulum|nascetur)\b", re.IGNORECASE)


def _looks_like_directory(text: str) -> bool:
    """Careers indexes and placeholder marketing pages are not job postings."""
    if _LOREM_RE.search(text):
        return True
    titles = _ROLE_TITLE_RE.findall(text)
    return len(titles) >= 8


def _guess_title(chunk: str) -> str | None:
    match = _ROLE_TITLE_RE.search(chunk[:600])
    if not match:
        return None
    title = _WS_RE.sub(" ", match.group(0)).strip(" -–—")
    if not 6 <= len(title) <= 80:
        return None
    return title
