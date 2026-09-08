"""BambooHR skills client tests (HTTP mocked)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.skills.client import BambooHRClient, clear_catalog_cache
from services.skills.handler import EmployeeSkills, LookupSkillsRequest
from tests.helpers import assert_json_response_list, assert_model


def test_catalog_and_lookup_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("BAMBOOHR_API_KEY", "key")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "ioet")
    monkeypatch.setenv("BAMBOOHR_FETCH_DETAILS", "false")
    clear_catalog_cache()

    session = MagicMock()
    directory = MagicMock()
    directory.ok = True
    directory.content = b"{}"
    directory.json.return_value = {
        "employees": [
            {
                "id": "1",
                "displayName": "Grace Hopper",
                "jobTitle": "Engineer",
                "department": "Delivery",
                "skills": "Python, AWS",
                "workEmail": "grace@ioet.com",
                "mobilePhone": "555",
            }
        ]
    }
    session.get.return_value = directory

    client = BambooHRClient(session=session, cache_ttl_seconds=60)
    catalog = client.fetch_catalog()
    rows = assert_json_response_list(catalog, EmployeeSkills)
    assert len(rows) == 1
    row = rows[0]
    assert row.employee_id == "1"
    assert row.display_name == "Grace Hopper"
    assert row.skills == ["Python", "AWS"]
    assert all(isinstance(skill, str) for skill in row.skills)
    dumped = row.model_dump()
    assert "workEmail" not in dumped
    assert "mobilePhone" not in dumped

    matches = client.lookup(["python"])
    assert len(matches) == 1
    matched = assert_json_response_list(matches, EmployeeSkills)
    assert matched[0].skills == ["Python"]

    client.fetch_catalog()
    assert session.get.call_count == 1
    get_call = session.get.call_args
    assert "/employees/directory" in get_call.args[0]
    assert get_call.kwargs["auth"] == ("key", "x")


def test_skills_endpoints_return_typed_catalog(monkeypatch) -> None:
    monkeypatch.setenv("BAMBOOHR_API_KEY", "key")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "ioet")
    monkeypatch.setenv("BAMBOOHR_FETCH_DETAILS", "false")
    clear_catalog_cache()

    session = MagicMock()
    directory = MagicMock()
    directory.ok = True
    directory.content = b"{}"
    directory.json.return_value = {
        "employees": [
            {
                "id": "1",
                "displayName": "Grace Hopper",
                "jobTitle": "Engineer",
                "department": "Delivery",
                "skills": "Python",
            }
        ]
    }
    session.get.return_value = directory

    from services.skills import handler as skills_handler

    monkeypatch.setattr(skills_handler, "_client", lambda: BambooHRClient(session=session))

    from services.skills.app import app

    client = TestClient(app)
    catalog = client.get("/v1/catalog")
    assert catalog.status_code == 200
    employees = assert_json_response_list(catalog.json(), EmployeeSkills)
    assert employees[0].employee_id == "1"
    assert employees[0].display_name == "Grace Hopper"
    assert employees[0].skills == ["Python"]

    lookup_body = {"skills": ["Python"]}
    assert_model(lookup_body, LookupSkillsRequest)
    lookup = client.post("/v1/lookup", json=lookup_body)
    assert lookup.status_code == 200
    matched = assert_json_response_list(lookup.json(), EmployeeSkills)
    assert matched[0].skills == ["Python"]


def test_skills_endpoints_require_config(monkeypatch) -> None:
    monkeypatch.delenv("BAMBOOHR_API_KEY", raising=False)
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    clear_catalog_cache()
    from services.skills.app import app

    client = TestClient(app)
    assert client.get("/v1/catalog").status_code == 503
    assert client.post("/v1/lookup", json={"skills": ["Python"]}).status_code == 503
