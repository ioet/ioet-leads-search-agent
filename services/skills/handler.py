from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.skills.client import BambooHRClient, BambooHRConfigError, clear_catalog_cache

router = APIRouter(prefix="/v1", tags=["skills"])


class EmployeeSkills(BaseModel):
    employee_id: str
    display_name: str
    job_title: str | None = None
    department: str | None = None
    skills: list[str] = Field(default_factory=list)


class LookupSkillsRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)


def _client() -> BambooHRClient:
    return BambooHRClient()


@router.get("/catalog")
def get_skills_catalog() -> list[EmployeeSkills]:
    """Fetch normalized skills catalog from BambooHR."""
    try:
        rows = _client().fetch_catalog()
        return [EmployeeSkills.model_validate(row) for row in rows]
    except BambooHRConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/lookup")
def lookup_skills(request: LookupSkillsRequest) -> list[EmployeeSkills]:
    """Find employees matching requested skills."""
    try:
        rows = _client().lookup(request.skills)
        return [EmployeeSkills.model_validate(row) for row in rows]
    except BambooHRConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/cache/clear")
def clear_cache() -> dict[str, str]:
    """Drop the in-memory catalog cache (ops / tests)."""
    clear_catalog_cache()
    return {"status": "cleared"}
