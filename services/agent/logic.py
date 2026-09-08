"""Agent judgment: ICP scoring, skill matching, outreach email drafting."""

from __future__ import annotations

import logging
from typing import Any

from services.agent.bedrock import BedrockClient, BedrockConfigError, BedrockResponseError
from services.agent.prompts import (
    draft_outreach_email_system,
    draft_outreach_email_user,
    match_skills_system,
    match_skills_user,
    score_companies_system,
    score_companies_user,
)
from services.agent.skills_source import SkillsCatalogError, fetch_skills_catalog
from services.common.icp import IdealCustomerProfile, load_icp
from services.common.schemas import Company, LeadResult, LeadStatus, SkillMatch

logger = logging.getLogger(__name__)

SCORE_BATCH_SIZE = 15


def _merge_company_scores(original: Company, scored: dict[str, Any]) -> Company:
    data = original.model_dump()
    for key in ("icp_score", "rationale", "signals", "segment_id"):
        if key in scored and scored[key] is not None:
            data[key] = scored[key]
    return Company.model_validate(data)


def _index_scored_companies(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise BedrockResponseError(f"Score response must be object, got {type(raw)!r}")
    items = raw.get("companies")
    if not isinstance(items, list):
        raise BedrockResponseError("Score response missing companies[]")
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (item.get("domain") or item.get("name") or "").lower()
        if key:
            by_key[key] = item
    return by_key


def score_companies(
    icp: IdealCustomerProfile,
    companies: list[Company],
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> list[Company]:
    if not companies:
        return []
    client = bedrock or BedrockClient(model_id=model_id, complexity="high")
    scored: list[Company] = []
    for start in range(0, len(companies), SCORE_BATCH_SIZE):
        batch = companies[start : start + SCORE_BATCH_SIZE]
        raw = client.converse_json(
            score_companies_system(icp),
            score_companies_user(icp, batch),
        )
        index = _index_scored_companies(raw)
        for company in batch:
            key = (company.domain or company.name).lower()
            match = index.get(key)
            if match:
                scored.append(_merge_company_scores(company, match))
            else:
                logger.warning("No Bedrock score for company %s; keeping original", company.name)
                scored.append(company)
    return scored


def _parse_skill_matches(raw: Any) -> list[SkillMatch]:
    if not isinstance(raw, dict):
        raise BedrockResponseError(f"Match response must be object, got {type(raw)!r}")
    items = raw.get("skill_matches")
    if not isinstance(items, list):
        return []
    matches: list[SkillMatch] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            matches.append(SkillMatch.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping invalid skill match %r: %s", item, exc)
    return matches


def match_ioet_skills(
    lead: LeadResult,
    catalog: list[dict[str, Any]] | None = None,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> LeadResult:
    required = list(lead.job_context.required_skills) if lead.job_context else []
    if not required:
        logger.info(
            "No required skills on lead %s — skipping Bedrock match",
            lead.company.name,
        )
        return lead.model_copy(update={"skill_matches": [], "status": LeadStatus.MATCHED})

    if catalog is None:
        rows = fetch_skills_catalog()
    else:
        rows = catalog
    if not rows:
        logger.warning("Empty skills catalog; returning lead unchanged")
        return lead

    client = bedrock or BedrockClient(model_id=model_id, complexity="low")
    raw = client.converse_json(
        match_skills_system(),
        match_skills_user(lead, rows),
    )
    matches = _parse_skill_matches(raw)
    return lead.model_copy(
        update={"skill_matches": matches, "status": LeadStatus.MATCHED},
    )


def _format_outreach_email(raw: Any) -> str:
    if isinstance(raw, dict):
        subject = str(raw.get("subject") or "").strip()
        body = str(raw.get("body") or raw.get("email") or raw.get("note") or "").strip()
        if subject and body:
            return f"Subject: {subject}\n\n{body}"
        if body:
            return body
        if subject:
            return subject
    if isinstance(raw, str):
        return raw.strip()
    raise BedrockResponseError(f"Unexpected outreach email response: {raw!r}")


def draft_outreach_email(
    lead: LeadResult,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> str:
    """Draft a customer-centric outreach email for the primary contact."""
    client = bedrock or BedrockClient(model_id=model_id, complexity="high")
    raw = client.converse_json(
        draft_outreach_email_system(),
        draft_outreach_email_user(lead),
    )
    return _format_outreach_email(raw)


def draft_crm_note(
    lead: LeadResult,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> str:
    """Backward-compatible alias — drafts the HubSpot outreach email."""
    return draft_outreach_email(lead, bedrock=bedrock, model_id=model_id)


def load_icp_for_version(icp_version: str) -> IdealCustomerProfile:
    icp = load_icp()
    if icp_version != icp.version:
        raise ValueError(
            f"Unknown icp_version {icp_version!r}; loaded canonical {icp.version!r}"
        )
    return icp
