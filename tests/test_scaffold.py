"""Validate shared schemas and service app imports."""

from fastapi.testclient import TestClient

from services.common.schemas import Company, LeadResult, WorkflowRunInput
from tests.helpers import assert_model


def test_workflow_run_input_defaults(monkeypatch) -> None:
    monkeypatch.delenv("MAX_COMPANIES", raising=False)
    monkeypatch.delenv("MAX_CONTACTS_PER_COMPANY", raising=False)
    inp = WorkflowRunInput(icp_version="2026-08-26", campaign_id="test-campaign")
    assert inp.segment_ids == ["primary"]
    assert isinstance(inp.segment_ids, list)
    assert inp.max_leads == 25
    assert isinstance(inp.max_leads, int)
    assert inp.dry_run is False
    assert isinstance(inp.dry_run, bool)


def test_lead_result_roundtrip() -> None:
    lead = LeadResult(company=Company(name="Acme", domain="acme.com"))
    restored = assert_model(lead.model_dump(), LeadResult)
    assert restored.company.name == "Acme"
    assert restored.company.domain == "acme.com"
    assert restored.status.value == "discovered"


def test_service_health_endpoints() -> None:
    from services.agent.app import app as agent_app
    from services.apollo.app import app as apollo_app
    from services.hubspot.app import app as hubspot_app
    from services.jobs.app import app as jobs_app
    from services.notify.app import app as notify_app
    from services.skills.app import app as skills_app

    for app in (apollo_app, agent_app, skills_app, hubspot_app, jobs_app, notify_app):
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert body["status"] == "ok"
        assert isinstance(body["status"], str)
