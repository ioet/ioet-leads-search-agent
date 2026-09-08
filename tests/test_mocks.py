"""Smoke tests for mock microservices."""

from fastapi.testclient import TestClient

from mocks.apollo.app import app as apollo_app
from mocks.bamboo.app import app as bamboo_app
from mocks.hubspot.app import app as hubspot_app
from mocks.notify.app import app as notify_app
from services.common.icp import load_icp
from services.common.schemas import Company, CompanySearchRequest, Contact, LeadResult, LeadStatus, NotifyRequest
from tests.helpers import assert_json_response, assert_json_response_list, assert_model


def test_apollo_mock_search_and_contacts() -> None:
    icp = load_icp()
    client = TestClient(apollo_app)
    search_body = {
        "icp_version": icp.version,
        "segment_ids": ["primary"],
        "max_results": 2,
    }
    assert_model(search_body, CompanySearchRequest)
    companies = client.post("/v1/search-companies", json=search_body)
    assert companies.status_code == 200
    company_list = assert_json_response_list(companies.json(), Company)
    assert len(company_list) >= 1
    assert all(isinstance(c.name, str) and c.name for c in company_list)

    company = company_list[0].model_dump()
    contacts = client.post(
        "/v1/find-decision-makers",
        json={"company": company, "icp_version": icp.version},
    )
    assert contacts.status_code == 200
    contact_list = assert_json_response_list(contacts.json(), Contact)
    assert len(contact_list) >= 1
    assert all(isinstance(c.full_name, str) and c.full_name for c in contact_list)


def test_bamboo_mock_catalog_and_lookup() -> None:
    from services.skills.handler import EmployeeSkills, LookupSkillsRequest

    client = TestClient(bamboo_app)
    catalog = client.get("/v1/catalog")
    assert catalog.status_code == 200
    employees = assert_json_response_list(catalog.json(), EmployeeSkills)
    assert len(employees) >= 3
    assert all(isinstance(e.employee_id, str) for e in employees)
    assert all(isinstance(e.skills, list) for e in employees)

    lookup_body = {"skills": ["Python"]}
    assert_model(lookup_body, LookupSkillsRequest)
    matches = client.post("/v1/lookup", json=lookup_body)
    assert matches.status_code == 200
    matched = assert_json_response_list(matches.json(), EmployeeSkills)
    assert len(matched) >= 1
    assert all("Python" in e.skills or any(s.lower() == "python" for s in e.skills) for e in matched)


def test_hubspot_mock_upsert_dry_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_MOCK_OUTPUT_DIR", str(tmp_path))
    client = TestClient(hubspot_app)
    lead = {
        "company": {"name": "Acme", "domain": "acme.com"},
        "contacts": [{"full_name": "Ada", "title": "CTO"}],
        "skill_matches": [{"skill": "Python", "person_or_team": "Ana", "confidence": 0.9}],
        "notes": "Subject: Hello\n\nHi Ada, we can help with Python.",
    }
    assert_json_response(lead, LeadResult)
    response = client.post("/v1/upsert-lead", json={"lead": lead, "dry_run": True})
    assert response.status_code == 200
    upserted = assert_json_response(response.json(), LeadResult)
    assert upserted.hubspot_ids["company"].startswith("dry-run-company-")
    assert upserted.status == LeadStatus.PUBLISHED

    store = client.get("/v1/store")
    assert store.status_code == 200
    store_body = store.json()
    assert isinstance(store_body, dict)
    assert isinstance(store_body.get("companies"), dict)
    assert store_body["companies"]
    assert "acme.com" in store_body["companies"]
    assert store_body["_output_dir"] == str(tmp_path)

    store_file = tmp_path / "store.json"
    lead_file = tmp_path / "leads" / "acme.com.json"
    note_file = tmp_path / "leads" / "acme.com-note.txt"
    assert store_file.is_file()
    assert lead_file.is_file()
    assert note_file.is_file()
    assert "Subject: Hello" in note_file.read_text(encoding="utf-8")

    contact = next(iter(store_body["contacts"].values()))
    assert contact["company"]["domain"] == "acme.com"
    assert contact["company"]["name"] == "Acme"
    assert store_body["notes"][0]["company"]["domain"] == "acme.com"


def test_notify_mock_writes_slack_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MOCK_OUTPUT_DIR", str(tmp_path))
    client = TestClient(notify_app)

    notify_body = {
        "message": "Leads campaign `demo-001` (dry-run): 2 published.",
        "details": {"kind": "campaign_summary", "campaign_id": "demo-001"},
    }
    assert_model(notify_body, NotifyRequest)
    response = client.post("/v1/notify", json=notify_body)
    assert response.status_code == 200
    assert response.json()["status"] == "logged"

    failure_body = {
        "campaign_id": "demo-001",
        "error": "draft-outreach-email: ERROR",
        "step_name": "draft-outreach-email",
    }
    response = client.post("/v1/failure", json=failure_body)
    assert response.status_code == 200

    listed = client.get("/v1/messages")
    assert listed.status_code == 200
    body = listed.json()
    assert body["_output_dir"] == str(tmp_path)
    assert len(body["messages"]) == 2

    assert (tmp_path / "messages.json").is_file()
    assert (tmp_path / "latest-notify.txt").is_file()
    assert (tmp_path / "latest-failure.txt").is_file()
    assert (tmp_path / "slack-feed.txt").is_file()
    assert "demo-001" in (tmp_path / "latest-notify.txt").read_text(encoding="utf-8")
    assert "draft-outreach-email" in (tmp_path / "latest-failure.txt").read_text(encoding="utf-8")
