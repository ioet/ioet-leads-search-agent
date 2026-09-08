"""LinkedIn job posting source (API integration point)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from services.common.schemas import Company, JobPosting
from services.jobs.sources.base import JobPostingSource

logger = logging.getLogger(__name__)

LINKEDIN_JOBS_BASE_URL = os.environ.get(
    "LINKEDIN_JOBS_BASE_URL", "https://api.linkedin.com/v2"
).rstrip("/")


class LinkedInJobPostingSource(JobPostingSource):
    """Fetch job postings from LinkedIn when credentials are configured."""

    source_id = "linkedin"

    def __init__(
        self,
        access_token: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.access_token = (
            access_token if access_token is not None else os.environ.get("LINKEDIN_JOBS_ACCESS_TOKEN", "")
        ).strip()
        self.session = session or requests.Session()

    def search(self, company: Company, *, max_results: int = 10) -> list[JobPosting]:
        if not self.access_token:
            logger.info("LinkedIn jobs source skipped — LINKEDIN_JOBS_ACCESS_TOKEN not set")
            return []
        if not company.linkedin_url and not company.name:
            return []

        # Integration hook — replace with the real LinkedIn Jobs API query when wired.
        payload = self._query_api(company, max_results=max_results)
        return self._normalize(payload, max_results=max_results)

    def _query_api(self, company: Company, *, max_results: int) -> dict[str, Any]:
        _ = max_results
        logger.warning(
            "LinkedIn jobs API adapter not implemented yet for %s; returning empty set",
            company.name,
        )
        return {"elements": []}

    def _normalize(self, payload: dict[str, Any], *, max_results: int) -> list[JobPosting]:
        elements = payload.get("elements") or payload.get("jobs") or []
        postings: list[JobPosting] = []
        for raw in elements[:max_results]:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or raw.get("jobTitle") or "").strip()
            description = str(raw.get("description") or raw.get("jobDescription") or "").strip()
            if not title or not description:
                continue
            postings.append(
                JobPosting(
                    title=title,
                    source=self.source_id,
                    description=description,
                    url=raw.get("url") or raw.get("jobPostingUrl"),
                    location=raw.get("location") or raw.get("jobLocation"),
                )
            )
        return postings
