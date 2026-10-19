from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.common.schemas import LeadResult
from services.jobs.logic import extract_job_skills

router = APIRouter(prefix="/v1", tags=["jobs"])


def _parse_extract_body(body: dict[str, Any]) -> tuple[LeadResult, dict[str, Any] | None]:
    if "company" in body and "lead" not in body:
        return LeadResult.model_validate(body), None
    return LeadResult.model_validate(body["lead"]), body.get("campaign_config")


@router.post("/extract-job-skills")
def extract_job_skills_endpoint(body: dict[str, Any]) -> LeadResult:
    """Discover job postings and extract required skills for ioet matching."""
    try:
        lead, campaign_config = _parse_extract_body(body)
        return extract_job_skills(lead, campaign_config=campaign_config)
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
