"""Mock jobs service — fixture postings + optional Bedrock skill extraction."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mocks.common.logging import RequestResponseLogMiddleware, configure_logging
from mocks.data.fixtures import job_postings_for_company
from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.common.http import create_app
from services.common.schemas import JobPostingContext, LeadResult, LeadStatus
from services.jobs.extractor import extract_required_skills
from services.jobs.logic import format_job_posting_notes

configure_logging()
logger = logging.getLogger("mocks.jobs")
router = APIRouter(prefix="/v1", tags=["jobs-mock"])


class MockJobSourceConfig(BaseModel):
    sources_searched: list[str] = ["linkedin", "company_website"]


def _merge_notes(existing: str | None, addition: str) -> str:
    if existing and existing.strip():
        return f"{existing.strip()}\n\n{addition.strip()}"
    return addition.strip()


@router.post("/extract-job-skills")
def extract_job_skills_mock(lead: LeadResult) -> LeadResult:
    """Return fixture postings; extract skills via Bedrock when configured."""
    postings = job_postings_for_company(lead.company)
    sources = MockJobSourceConfig().sources_searched

    if not postings:
        note = f"No job postings found (searched: {', '.join(sources)})."
        context = JobPostingContext(
            postings=[],
            required_skills=[],
            sources_searched=sources,
            note=note,
        )
        return lead.model_copy(
            update={
                "job_context": context,
                "status": LeadStatus.ENRICHED,
            }
        )

    try:
        required_skills = extract_required_skills(postings)
    except BedrockConfigError as exc:
        # Offline fallback for tests without Bedrock.
        required_skills = _fallback_skills(postings)
        if not os.environ.get("AWS_BEDROCK_API_KEY", "").strip() and not required_skills:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    note = (
        f"Found {len(postings)} job posting(s) via {', '.join(sources)}; "
        f"extracted {len(required_skills)} required skill(s)."
    )
    context = JobPostingContext(
        postings=postings,
        required_skills=required_skills,
        sources_searched=sources,
        note=note,
    )
    links = format_job_posting_notes(postings)
    company = lead.company
    if links:
        company = company.model_copy(update={"notes": _merge_notes(company.notes, links)})
    return lead.model_copy(
        update={
            "company": company,
            "job_context": context,
            "status": LeadStatus.ENRICHED,
        }
    )


def _fallback_skills(postings: list) -> list[str]:
    """Deterministic skill list for unit tests when Bedrock is unavailable."""
    keywords = {
        "python": "Python",
        "fastapi": "FastAPI",
        "postgresql": "PostgreSQL",
        "aws": "AWS",
        "kubernetes": "Kubernetes",
        "terraform": "Terraform",
        "java": "Java",
        "spring": "Spring",
        "pytorch": "PyTorch",
        "mlops": "MLOps",
        "llm": "LLM",
        "react": "React",
        "fintech": "fintech",
        "payments": "payments",
    }
    blob = " ".join(p.description.lower() for p in postings)
    found: list[str] = []
    seen: set[str] = set()
    for key, label in keywords.items():
        if key in blob and label.lower() not in seen:
            seen.add(label.lower())
            found.append(label)
    return found


app = create_app("jobs-mock")
app.add_middleware(RequestResponseLogMiddleware, service_name="jobs-mock")
app.include_router(router)
