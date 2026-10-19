"""Agent judgment: ICP scoring, skill matching, outreach email drafting."""

from __future__ import annotations

import logging
import re
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
from services.common.campaign_config import EmailDraftConfig
from services.common.icp import IdealCustomerProfile
from services.common.icp_ref import load_icp_for_request
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
    usable = [row for row in rows if (row.get("skills") or [])]
    if not usable:
        logger.warning("Skills catalog has no skill values; skipping Bedrock match for %s", lead.company.name)
        return lead.model_copy(update={"skill_matches": [], "status": LeadStatus.MATCHED})

    client = bedrock or BedrockClient(model_id=model_id, complexity="low")
    try:
        raw = client.converse_json(
            match_skills_system(),
            match_skills_user(lead, usable),
            allow_repair=False,
        )
    except BedrockResponseError as exc:
        logger.warning("Rejecting unparseable skill match for %s: %s", lead.company.name, exc)
        note = "Skill match was discarded because the model response was truncated."
        return lead.model_copy(
            update={"skill_matches": [], "notes": _merge_lead_notes(lead.notes, note)}
        )
    parsed = _parse_skill_matches(raw)
    matches = _plausible_matches(parsed)
    if parsed and not matches:
        note = "Skill match was discarded because one person was attached to most of the list."
        return lead.model_copy(
            update={"skill_matches": [], "notes": _merge_lead_notes(lead.notes, note)}
        )
    return lead.model_copy(
        update={"skill_matches": matches, "status": LeadStatus.MATCHED},
    )


def _merge_lead_notes(existing: str | None, addition: str) -> str:
    if existing and existing.strip():
        return f"{existing.strip()}\n\n{addition.strip()}"
    return addition.strip()


def _plausible_matches(matches: list[SkillMatch]) -> list[SkillMatch]:
    """Cap the list and drop a match-all assignment to a single person."""
    capped = matches[:8]
    if not capped:
        return []
    counts: dict[str, int] = {}
    for match in capped:
        key = match.person_or_team.strip().lower()
        counts[key] = counts.get(key, 0) + 1
    top = max(counts.values())
    if top >= 6 or (len(capped) >= 4 and top / len(capped) >= 0.6):
        logger.warning(
            "Rejecting %d skill matches; %d belong to one person",
            len(capped),
            top,
        )
        return []
    return capped


_GENERIC_GREETING = re.compile(
    r"^(?:hi|hello|hey)(?:\s+there)?\s*[,!.\-—:]*\s*",
    re.IGNORECASE,
)


def _greeting_name(full_name: str | None) -> str | None:
    if not full_name or not full_name.strip():
        return None
    return full_name.strip().split()[0]


def _address_contact(email: str, full_name: str | None) -> str:
    """Open the email body with the contact's first name."""
    first = _greeting_name(full_name)
    if not first:
        return email

    subject = ""
    body = email
    if email.startswith("Subject:"):
        subject, _, rest = email.partition("\n\n")
        body = rest

    stripped = body.strip()
    if re.match(rf"^(?:hi|hello|hey)\s+{re.escape(first)}\b", stripped, re.IGNORECASE):
        addressed = stripped
    else:
        remainder = _GENERIC_GREETING.sub("", stripped, count=1).strip()
        addressed = f"Hi {first},\n\n{remainder}" if remainder else f"Hi {first},"

    if subject:
        return f"{subject}\n\n{addressed}" if addressed else subject
    return addressed


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
    email_config: EmailDraftConfig | None = None,
) -> str:
    """Draft a customer-centric outreach email for the primary contact."""
    client = bedrock or BedrockClient(model_id=model_id, complexity="high")
    raw = client.converse_json(
        draft_outreach_email_system(),
        draft_outreach_email_user(lead, email_config=email_config),
    )
    email = _format_outreach_email(raw)
    contact_name = lead.contacts[0].full_name if lead.contacts else None
    return _address_contact(email, contact_name)


def draft_crm_note(
    lead: LeadResult,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
    email_config: EmailDraftConfig | None = None,
) -> str:
    """Backward-compatible alias — drafts the HubSpot outreach email."""
    return draft_outreach_email(
        lead, bedrock=bedrock, model_id=model_id, email_config=email_config
    )


def load_icp_for_version(
    icp_version: str | None = None,
    *,
    icp_ref: str | None = None,
) -> IdealCustomerProfile:
    return load_icp_for_request(icp_ref=icp_ref, icp_version=icp_version)
