"""Job posting discovery + skill extraction orchestration."""

from __future__ import annotations

import logging
import os

from services.agent.bedrock import BedrockClient, BedrockConfigError, BedrockResponseError
from services.common.schemas import JobPosting, JobPostingContext, LeadResult, LeadStatus
from services.jobs.extractor import extract_required_skills
from services.jobs.sources.registry import get_enabled_sources

logger = logging.getLogger(__name__)

MAX_POSTINGS_PER_SOURCE = int(os.environ.get("JOB_POSTINGS_MAX_PER_SOURCE", "5"))


def _merge_notes(existing: str | None, addition: str) -> str:
    if existing and existing.strip():
        return f"{existing.strip()}\n\n{addition.strip()}"
    return addition.strip()


def format_job_posting_notes(postings: list[JobPosting]) -> str | None:
    """Company-note body: one link per job posting that has a URL."""
    lines = [f"- {posting.title}: {posting.url}" for posting in postings if posting.url]
    if not lines:
        return None
    return "Job postings:\n" + "\n".join(lines)


def _with_job_links(lead: LeadResult, postings: list[JobPosting]) -> LeadResult:
    addition = format_job_posting_notes(postings)
    if not addition:
        return lead
    notes = _merge_notes(lead.company.notes, addition)
    company = lead.company.model_copy(update={"notes": notes})
    return lead.model_copy(update={"company": company})


def discover_job_postings(lead: LeadResult) -> tuple[list[JobPosting], list[str]]:
    """Query all enabled sources; never raises — per-source failures are logged."""
    sources = get_enabled_sources()
    if not sources:
        logger.warning("No job posting sources enabled")
        return [], []

    all_postings: list[JobPosting] = []
    searched: list[str] = []
    company = lead.company

    for source in sources:
        searched.append(source.source_id)
        try:
            found = source.search(company, max_results=MAX_POSTINGS_PER_SOURCE)
            all_postings.extend(found)
            logger.info(
                "Job source %s returned %d posting(s) for %s",
                source.source_id,
                len(found),
                company.name,
            )
        except Exception as exc:
            logger.warning("Job source %s failed for %s: %s", source.source_id, company.name, exc)

    return all_postings, searched


def extract_job_skills(
    lead: LeadResult,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> LeadResult:
    """Search job postings and attach required skills to the lead."""
    postings, sources_searched = discover_job_postings(lead)

    if not postings:
        note = (
            "No job postings found"
            + (f" (searched: {', '.join(sources_searched)})" if sources_searched else "")
            + "."
        )
        context = JobPostingContext(
            postings=[],
            required_skills=[],
            sources_searched=sources_searched,
            note=note,
        )
        return lead.model_copy(
            update={
                "job_context": context,
                "status": LeadStatus.ENRICHED,
            }
        )

    try:
        required_skills = extract_required_skills(
            postings, bedrock=bedrock, model_id=model_id
        )
    except (BedrockConfigError, BedrockResponseError) as exc:
        logger.error("Skill extraction failed for %s: %s", lead.company.name, exc)
        raise

    sources_label = ", ".join(sources_searched) if sources_searched else "unknown"
    note = (
        f"Found {len(postings)} job posting(s) via {sources_label}; "
        f"extracted {len(required_skills)} required skill(s)."
    )
    if not required_skills:
        note = (
            f"Found {len(postings)} job posting(s) via {sources_label}, "
            "but no required skills could be extracted."
        )

    context = JobPostingContext(
        postings=postings,
        required_skills=required_skills,
        sources_searched=sources_searched,
        note=note,
    )
    return _with_job_links(lead, postings).model_copy(
        update={
            "job_context": context,
            "status": LeadStatus.ENRICHED,
        }
    )
