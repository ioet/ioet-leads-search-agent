from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.common.schemas import LeadResult
from services.jobs.logic import extract_job_skills

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.post("/extract-job-skills")
def extract_job_skills_endpoint(lead: LeadResult) -> LeadResult:
    """Discover job postings and extract required skills for ioet matching."""
    try:
        return extract_job_skills(lead)
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
