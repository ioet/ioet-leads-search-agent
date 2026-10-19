"""Job posting discovery + skill extraction orchestration."""

from __future__ import annotations

import logging
import os

from services.agent.bedrock import BedrockClient, BedrockConfigError, BedrockResponseError
from services.common.campaign_config import HiringSignalConfig, parse_campaign_config
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


def discover_job_postings(
    lead: LeadResult,
    source_ids: list[str] | None = None,
) -> tuple[list[JobPosting], list[str]]:
    """Query enabled sources; never raises — per-source failures are logged."""
    sources = get_enabled_sources(source_ids)
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


def _hiring_signal(campaign_config: dict | None) -> HiringSignalConfig:
    return parse_campaign_config(campaign_config).hiring_signal_config


def _known_source_ids(requested: list[str]) -> list[str]:
    from services.jobs.sources.registry import _SOURCE_FACTORIES

    known: list[str] = []
    for source_id in requested:
        if source_id in _SOURCE_FACTORIES:
            known.append(source_id)
        else:
            logger.info("Ignoring job source %r; no connector is registered", source_id)
    return known


def _posting_text(posting: JobPosting) -> str:
    return f"{posting.title} {posting.description} {posting.location or ''}".lower()


def _filter_postings(postings: list[JobPosting], signal: HiringSignalConfig) -> list[JobPosting]:
    roles = [item.strip().lower() for item in signal.role_categories if item.strip()]
    keywords = [item.strip().lower() for item in signal.job_keywords if item.strip()]
    locations = [item.strip().lower() for item in signal.job_locations if item.strip()]
    kept: list[JobPosting] = []
    for posting in postings:
        text = _posting_text(posting)
        if roles and not any(role in text for role in roles):
            continue
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        if locations and not any(location in text for location in locations):
            continue
        kept.append(posting)
    return kept


def _ground_skills(skills: list[str], postings: list[JobPosting]) -> list[str]:
    """Keep skills that appear in the posting text, and drop directory-sized lists."""
    blob = " ".join(_posting_text(posting) for posting in postings)
    grounded: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        key = skill.strip().lower()
        if not key or key in seen or key not in blob:
            continue
        seen.add(key)
        grounded.append(skill.strip())
        if len(grounded) >= 12:
            break
    if len(skills) >= 20 and len(grounded) <= 2:
        logger.warning(
            "Discarding %d extracted skills; almost none appear in the posting text",
            len(skills),
        )
        return []
    return grounded


def _job_context(
    postings: list[JobPosting],
    skills: list[str],
    sources_searched: list[str],
    note: str,
) -> JobPostingContext:
    return JobPostingContext(
        postings=postings,
        required_skills=skills,
        sources_searched=sources_searched,
        note=note,
    )


def extract_job_skills(
    lead: LeadResult,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
    campaign_config: dict | None = None,
) -> LeadResult:
    """Search job postings, apply the hiring signal, and attach required skills."""
    signal = _hiring_signal(campaign_config) if campaign_config else None
    if signal and (signal.posted_within_days or signal.open_longer_than_days):
        logger.info(
            "Hiring-signal date filters are not applied; job postings have no dates "
            "(posted_within_days=%s, open_longer_than_days=%s)",
            signal.posted_within_days,
            signal.open_longer_than_days,
        )

    source_ids = _known_source_ids(signal.sources) if signal else None
    postings, sources_searched = discover_job_postings(lead, source_ids=source_ids)
    matched = _filter_postings(postings, signal) if signal else postings
    minimum = (signal.min_open_eng_roles or 0) if signal else 0
    enough = len(matched) >= minimum if minimum else bool(matched)
    sources_label = ", ".join(sources_searched) if sources_searched else "none"

    if signal and signal.mode.value == "required" and not enough:
        note = (
            f"Skipped: hiring signal required {minimum or 1} matching role(s) "
            f"but found {len(matched)} (searched: {sources_label})."
        )
        return lead.model_copy(
            update={
                "job_context": _job_context(matched, [], sources_searched, note),
                "status": LeadStatus.SKIPPED,
                "notes": _merge_notes(lead.notes, note),
            }
        )

    if not matched:
        note = f"No job postings found (searched: {sources_label})."
        return lead.model_copy(
            update={
                "job_context": _job_context([], [], sources_searched, note),
                "status": LeadStatus.ENRICHED,
                "notes": _merge_notes(lead.notes, note),
            }
        )

    try:
        required_skills = _ground_skills(
            extract_required_skills(matched, bedrock=bedrock, model_id=model_id),
            matched,
        )
    except (BedrockConfigError, BedrockResponseError) as exc:
        logger.error("Skill extraction failed for %s: %s", lead.company.name, exc)
        raise

    note = (
        f"Found {len(matched)} matching job posting(s) via {sources_label}; "
        f"extracted {len(required_skills)} required skill(s)."
    )
    return _with_job_links(lead, matched).model_copy(
        update={
            "job_context": _job_context(matched, required_skills, sources_searched, note),
            "status": LeadStatus.ENRICHED,
            "notes": _merge_notes(lead.notes, note),
        }
    )
