"""Register and resolve enabled job-posting sources."""

from __future__ import annotations

import logging
import os

from services.jobs.sources.base import JobPostingSource
from services.jobs.sources.company_website import CompanyWebsiteJobPostingSource
from services.jobs.sources.linkedin import LinkedInJobPostingSource

logger = logging.getLogger(__name__)

_SOURCE_FACTORIES: dict[str, type[JobPostingSource]] = {
    "linkedin": LinkedInJobPostingSource,
    "company_website": CompanyWebsiteJobPostingSource,
}


def register_source(source_id: str, factory: type[JobPostingSource]) -> None:
    """Register an additional source implementation at runtime."""
    _SOURCE_FACTORIES[source_id] = factory


def get_enabled_sources() -> list[JobPostingSource]:
    """Instantiate sources listed in ``JOB_POSTING_SOURCES`` (comma-separated)."""
    raw = os.environ.get("JOB_POSTING_SOURCES", "linkedin,company_website")
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    sources: list[JobPostingSource] = []
    for source_id in ids:
        factory = _SOURCE_FACTORIES.get(source_id)
        if factory is None:
            logger.warning("Unknown job posting source %r — skipping", source_id)
            continue
        sources.append(factory())
    return sources
