from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.agent.logic import (
    draft_outreach_email,
    load_icp_for_version,
    match_ioet_skills,
    score_companies,
)
from services.agent.skills_source import SkillsCatalogError
from services.common.campaign_config import parse_campaign_config
from services.common.schemas import Company, LeadResult, LeadStatus

router = APIRouter(prefix="/v1", tags=["agent"])


class ScoreCompaniesRequest(BaseModel):
    icp_version: str | None = None
    icp_ref: str | None = None
    companies: list[Company] = Field(default_factory=list)
    campaign_config: dict[str, Any] | None = None
    model_id: str | None = None


class MatchSkillsRequest(BaseModel):
    lead: LeadResult
    skills_catalog: list[dict[str, Any]] | None = None
    model_id: str | None = None


def _parse_draft_outreach_body(
    body: dict[str, Any],
) -> tuple[LeadResult, str | None, dict[str, Any] | None]:
    """Accept either ``{lead, model_id?, campaign_config?}`` or a bare ``LeadResult``."""
    model_id = body.get("model_id")
    if not isinstance(model_id, str):
        model_id = None
    campaign_config = body.get("campaign_config")
    if not isinstance(campaign_config, dict):
        campaign_config = None
    if isinstance(body.get("lead"), dict):
        return LeadResult.model_validate(body["lead"]), model_id, campaign_config
    return LeadResult.model_validate(body), model_id, campaign_config


@router.post("/score-companies")
def score_companies_endpoint(request: ScoreCompaniesRequest) -> list[Company]:
    """Rank companies against ICP soft signals via AWS Bedrock."""
    try:
        icp = load_icp_for_version(request.icp_version, icp_ref=request.icp_ref)
        return score_companies(icp, request.companies, model_id=request.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/match-skills")
def match_skills_endpoint(request: MatchSkillsRequest) -> LeadResult:
    """Match lead to ioet skills via Bedrock + preloaded skills catalog."""
    try:
        return match_ioet_skills(
            request.lead, catalog=request.skills_catalog, model_id=request.model_id
        )
    except SkillsCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _attach_email_to_primary_contact(lead: LeadResult, email: str) -> LeadResult:
    """Store the outreach draft on the primary contact, leaving company notes alone."""
    if not lead.contacts:
        return lead
    contacts = list(lead.contacts)
    contacts[0] = contacts[0].model_copy(update={"notes": email})
    return lead.model_copy(update={"contacts": contacts})


@router.post("/draft-outreach-email")
def draft_outreach_email_endpoint(body: dict[str, Any]) -> LeadResult:
    """Draft a customer-centric outreach email and attach it to the primary contact notes.

    Accepts either ``{"lead": {...}, "model_id": "...", "campaign_config": {...}}``
    or a bare lead object.
    """
    try:
        lead, model_id, campaign_config = _parse_draft_outreach_body(body)
        if lead.status == LeadStatus.SKIPPED or not lead.contacts:
            return lead
        cfg = parse_campaign_config(campaign_config)
        email = draft_outreach_email(
            lead, model_id=model_id, email_config=cfg.email_draft_config
        )
        return _attach_email_to_primary_contact(lead, email)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/draft-crm-note")
def draft_crm_note_endpoint(body: dict[str, Any]) -> dict[str, str]:
    """Deprecated alias — returns outreach email as {note}. Prefer /v1/draft-outreach-email."""
    try:
        lead, model_id, campaign_config = _parse_draft_outreach_body(body)
        if lead.status == LeadStatus.SKIPPED or not lead.contacts:
            return {"note": ""}
        cfg = parse_campaign_config(campaign_config)
        email = draft_outreach_email(
            lead, model_id=model_id, email_config=cfg.email_draft_config
        )
        return {"note": email}
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
