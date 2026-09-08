"""Mock BambooHR / skills microservice — same HTTP contract as services/skills."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from mocks.common.logging import RequestResponseLogMiddleware, configure_logging
from mocks.data.fixtures import MOCK_EMPLOYEES, lookup_employees

configure_logging()
router = APIRouter(prefix="/v1", tags=["bamboo-mock"])


class EmployeeSkills(BaseModel):
    employee_id: str
    display_name: str
    job_title: str | None = None
    department: str | None = None
    skills: list[str] = Field(default_factory=list)


class LookupSkillsRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "bamboo-mock", "status": "ok"}


@router.get("/catalog")
def get_skills_catalog() -> list[EmployeeSkills]:
    return [EmployeeSkills.model_validate(row) for row in MOCK_EMPLOYEES]


@router.post("/lookup")
def lookup_skills(request: LookupSkillsRequest) -> list[EmployeeSkills]:
    rows = lookup_employees(request.skills)
    return [EmployeeSkills.model_validate(row) for row in rows]


@router.post("/cache/clear")
def clear_cache() -> dict[str, str]:
    return {"status": "cleared"}


app = FastAPI(title="bamboo-mock", version="0.1.0")
app.add_middleware(RequestResponseLogMiddleware, service_name="bamboo-mock")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bamboo-mock"}


app.include_router(router)
