"""BambooHR skills client tests (HTTP mocked)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.skills.client import BambooHRClient, clear_catalog_cache
from services.skills.handler import EmployeeSkills, LookupSkillsRequest
from services.skills.skill_fields import display_skill_name, skills_from_level_fields
from tests.helpers import assert_json_response_list, assert_model


def test_display_skill_name() -> None:
    assert display_skill_name("customAWS") == "AWS"
    assert display_skill_name("customPython") == "Python"
    assert display_skill_name("customNETCoreNET5") == "NETCoreNET5"


def test_skills_from_level_fields() -> None:
    detail = {
        "id": "1",
        "customAWS": "4",
        "customPython": 5,
        "customDocker": "0",
        "customCEDULA": "123",
        "customGit": None,
        "jobTitle": "Engineer",
    }
    skills = skills_from_level_fields(
        detail,
        ["customAWS", "customPython", "customDocker", "customGit"],
        min_level=1,
        max_level=5,
    )
    assert skills == ["AWS", "Python"]


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

    client = BambooHRClient(session=session, cache_ttl_seconds=60, skill_fields=[])
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

    monkeypatch.setattr(
        skills_handler,
        "_client",
        lambda: BambooHRClient(session=session, skill_fields=[]),
    )

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


def test_catalog_builds_skills_from_level_fields(monkeypatch) -> None:
    monkeypatch.setenv("BAMBOOHR_API_KEY", "key")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "ioet")
    monkeypatch.setenv("BAMBOOHR_FETCH_DETAILS", "true")
    clear_catalog_cache()

    session = MagicMock()
    skill_fields = ["customAWS", "customPython", "customDocker"]

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.ok = True
        resp.content = b"{}"
        if url.endswith("/employees/directory"):
            resp.json.return_value = {
                "employees": [
                    {
                        "id": "1",
                        "displayName": "Ada Lovelace",
                        "jobTitle": "Engineer",
                        "department": "Delivery",
                    }
                ]
            }
        elif "/employees/1" in url:
            fields = (kwargs.get("params") or {}).get("fields", "")
            if not fields and "fields=" in url:
                fields = url.split("fields=", 1)[1].split("&", 1)[0]
            data: dict = {"id": "1"}
            if "jobTitle" in fields:
                data["jobTitle"] = "Engineer"
                data["department"] = "Delivery"
            if "customAWS" in fields:
                data["customAWS"] = 4
            if "customPython" in fields:
                data["customPython"] = "5"
            if "customDocker" in fields:
                data["customDocker"] = None
            resp.json.return_value = data
        else:
            resp.json.return_value = {}
        return resp

    session.get.side_effect = fake_get
    client = BambooHRClient(
        session=session,
        cache_ttl_seconds=60,
        skill_fields=skill_fields,
    )
    catalog = client.fetch_catalog()
    rows = assert_json_response_list(catalog, EmployeeSkills)
    assert len(rows) == 1
    assert rows[0].skills == ["AWS", "Python"]
    # Literal commas in fields= (not %2C) — Bamboo ignores encoded lists.
    employee_calls = [
        call.args[0]
        for call in session.get.call_args_list
        if "/employees/1" in call.args[0]
    ]
    assert employee_calls
    assert "%2C" not in employee_calls[0]
    assert "fields=jobTitle,department," in employee_calls[0]
    assert "customAWS" in employee_calls[0]


def test_catalog_fetches_employee_details_in_parallel(monkeypatch) -> None:
    import threading
    import time

    monkeypatch.setenv("BAMBOOHR_API_KEY", "key")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "ioet")
    monkeypatch.setenv("BAMBOOHR_FETCH_DETAILS", "true")
    clear_catalog_cache()

    ids = [str(i) for i in range(1, 9)]
    lock = threading.Lock()
    in_flight = 0
    peak = 0

    def fake_get(url, **kwargs):
        nonlocal in_flight, peak
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.content = b"{}"
        if url.endswith("/employees/directory"):
            resp.json.return_value = {
                "employees": [{"id": i, "displayName": f"Emp {i}"} for i in ids]
            }
            return resp
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        emp_id = url.split("/employees/", 1)[1].split("?", 1)[0]
        resp.json.return_value = {"id": emp_id, "customPython": 4}
        return resp

    session = MagicMock()
    session.get.side_effect = fake_get
    client = BambooHRClient(session=session, cache_ttl_seconds=60, skill_fields=["customPython"])
    catalog = client.fetch_catalog()

    assert [row["employee_id"] for row in catalog] == ids
    assert all(row["skills"] == ["Python"] for row in catalog)
    assert peak > 1
