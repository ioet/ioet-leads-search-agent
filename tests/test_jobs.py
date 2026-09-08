"""Job posting discovery and skill extraction tests."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from services.common.schemas import Company, Contact, JobPosting, LeadResult, LeadStatus
from services.jobs.extractor import extract_required_skills
from services.jobs.logic import discover_job_postings, extract_job_skills
from services.jobs.sources.base import JobPostingSource
from services.jobs.sources.registry import register_source
from tests.helpers import assert_json_response


class _StubSource(JobPostingSource):
    def __init__(self, source_id: str, postings: list[JobPosting]) -> None:
        self._id = source_id
        self._postings = postings

    @property
    def source_id(self) -> str:
        return self._id

    def search(self, company: Company, *, max_results: int = 10) -> list[JobPosting]:
        return self._postings[:max_results]


def _sample_lead() -> LeadResult:
    return LeadResult(
        company=Company(name="Acme", domain="acme.com", industry="fintech"),
        contacts=[Contact(full_name="Ada", title="CTO")],
        status=LeadStatus.ENRICHED,
    )


def test_extract_required_skills_from_postings() -> None:
    postings = [
        JobPosting(
            title="Backend Engineer",
            source="linkedin",
            description="Python, FastAPI, AWS, PostgreSQL required.",
        )
    ]
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {
        "required_skills": ["Python", "FastAPI", "AWS", "PostgreSQL"]
    }
    skills = extract_required_skills(postings, bedrock=bedrock)
    assert skills == ["Python", "FastAPI", "AWS", "PostgreSQL"]
    assert all(isinstance(s, str) for s in skills)
    system_arg, user_arg = bedrock.converse_json.call_args[0]
    assert isinstance(system_arg, str)
    assert "Backend Engineer" in user_arg


def test_extract_required_skills_uses_low_complexity_client() -> None:
    postings = [JobPosting(title="Eng", source="linkedin", description="Python")]
    with patch("services.jobs.extractor.BedrockClient") as client_cls:
        client_cls.return_value.converse_json.return_value = {"required_skills": ["Python"]}
        extract_required_skills(postings, model_id="custom-low")
        client_cls.assert_called_once_with(model_id="custom-low", complexity="low")


def test_extract_job_skills_no_postings() -> None:
    register_source("_test_empty", lambda: _StubSource("_test_empty", []))
    with patch.dict("os.environ", {"JOB_POSTING_SOURCES": "_test_empty"}):
        result = extract_job_skills(_sample_lead())
    validated = assert_json_response(result.model_dump(), LeadResult)
    assert validated.job_context is not None
    assert validated.job_context.postings == []
    assert validated.job_context.required_skills == []
    assert validated.job_context.note is not None
    assert "No job postings found" in validated.job_context.note
    assert validated.notes is not None
    assert "No job postings found" in validated.notes


def test_extract_job_skills_with_postings() -> None:
    posting = JobPosting(
        title="Platform Engineer",
        source="company_website",
        description="Terraform, Kubernetes, AWS.",
        url="https://acme.com/careers",
    )
    register_source("_test_with_jobs", lambda: _StubSource("_test_with_jobs", [posting]))
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {"required_skills": ["Terraform", "Kubernetes", "AWS"]}

    with patch.dict("os.environ", {"JOB_POSTING_SOURCES": "_test_with_jobs"}):
        result = extract_job_skills(_sample_lead(), bedrock=bedrock)

    validated = assert_json_response(result.model_dump(), LeadResult)
    assert validated.job_context is not None
    assert len(validated.job_context.postings) == 1
    assert validated.job_context.postings[0].title == "Platform Engineer"
    assert validated.job_context.required_skills == ["Terraform", "Kubernetes", "AWS"]
    assert validated.job_context.sources_searched == ["_test_with_jobs"]


def test_discover_job_postings_aggregates_sources() -> None:
    p1 = JobPosting(title="A", source="s1", description="Python")
    p2 = JobPosting(title="B", source="s2", description="React")
    register_source("_test_a", lambda: _StubSource("_test_a", [p1]))
    register_source("_test_b", lambda: _StubSource("_test_b", [p2]))
    with patch.dict("os.environ", {"JOB_POSTING_SOURCES": "_test_a,_test_b"}):
        postings, searched = discover_job_postings(_sample_lead())
    assert len(postings) == 2
    assert searched == ["_test_a", "_test_b"]


def test_jobs_endpoint_returns_typed_lead(monkeypatch) -> None:
    monkeypatch.setenv("JOB_POSTING_SOURCES", "_test_empty_ep")
    register_source("_test_empty_ep", lambda: _StubSource("_test_empty_ep", []))
    from services.jobs.app import app

    client = TestClient(app)
    lead_body = _sample_lead().model_dump()
    response = client.post("/v1/extract-job-skills", json=lead_body)
    assert response.status_code == 200
    validated = assert_json_response(response.json(), LeadResult)
    assert validated.job_context is not None
    assert "No job postings found" in (validated.job_context.note or "")
