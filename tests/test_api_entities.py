"""Campaign API entity CRUD tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest_api import make_api_client, sample_icp_dict, signup_verify_login


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    yield from make_api_client()


def test_icp_campaign_schedule_run_crud(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    signup_verify_login(api_client, capsys=capsys)
    icp_payload = sample_icp_dict()

    created_icp = api_client.post(
        "/api/icps",
        json={"title": "Remote-Hiring Nearshore", "icp": icp_payload},
    )
    assert created_icp.status_code == 201, created_icp.text
    icp = created_icp.json()
    assert icp["title"] == "Remote-Hiring Nearshore"
    assert icp["icp_json_s3_uri"].startswith("local://")
    assert "icp" not in icp  # JSON body must not live on the metadata record

    listed = api_client.get("/api/icps")
    assert listed.status_code == 200
    assert any(row["icp_id"] == icp["icp_id"] for row in listed.json())

    doc = api_client.get(f"/api/icps/{icp['icp_id']}/document")
    assert doc.status_code == 200
    assert doc.json()["icp"]["version"] == icp_payload["version"]

    campaign_resp = api_client.post(
        "/api/campaigns",
        json={
            "name": "US SaaS hiring backend — Q4",
            "icp_id": icp["icp_id"],
            "start_date": "2026-10-13",
            "status": "draft",
            "config": {
                "run_mode": "dry_run",
                "companies_per_run": 10,
                "company_goal": 300,
                "credit_budget_per_run": 250,
                "decision_makers_config": {
                    "personas": ["CTO", "VP Engineering"],
                    "contacts_per_company": 2,
                },
            },
        },
    )
    assert campaign_resp.status_code == 201, campaign_resp.text
    campaign = campaign_resp.json()
    assert campaign["status"] == "draft"
    assert campaign["owner_name"] == "dev@ioet.com"
    assert campaign["owner_user_id"]
    directory = api_client.get("/api/users/directory")
    assert directory.status_code == 200
    assert any(
        row["user_id"] == campaign["owner_user_id"] and row["name"] == "dev@ioet.com"
        for row in directory.json()
    )
    assert campaign["config"]["companies_per_run"] == 10
    assert campaign["config"]["company_goal"] == 300
    assert campaign["config"]["credit_budget_per_run"] == 250
    assert campaign["companies_upserted"] == 0
    assert campaign["config"]["decision_makers_config"]["personas"] == [
        "CTO",
        "VP Engineering",
    ]

    patched = api_client.patch(
        f"/api/campaigns/{campaign['campaign_id']}",
        json={"status": "active"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "active"

    from unittest.mock import patch

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-sched-test-001",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        schedule_resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 7 * * 1",
                "timezone": "America/New_York",
                "enabled": True,
            },
        )
    assert schedule_resp.status_code == 201, schedule_resp.text
    schedule = schedule_resp.json()
    assert schedule["lh_schedule_id"] == "lh-sched-test-001"

    schedules = api_client.get(f"/api/campaigns/{campaign['campaign_id']}/schedules")
    assert schedules.status_code == 200
    assert len(schedules.json()) == 1

    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-run-test-001",
    ):
        run_resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        )
    assert run_resp.status_code == 201, run_resp.text
    run = run_resp.json()
    assert run["status"] == "running"
    assert run["lh_wf_run_id"] == "wf-run-test-001"
    assert run["campaign_name"] == campaign["name"]
    assert run["trigger"] == "manual"

    runs = api_client.get(f"/api/campaigns/{campaign['campaign_id']}/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 1

    got_run = api_client.get(f"/api/runs/{run['run_id']}")
    assert got_run.status_code == 200
    assert got_run.json()["run_id"] == run["run_id"]

    # Campaign create rejects unknown ICP
    bad = api_client.post(
        "/api/campaigns",
        json={"name": "x", "icp_id": "missing"},
    )
    assert bad.status_code == 400


def test_entities_require_auth(api_client: TestClient) -> None:
    assert api_client.get("/api/icps").status_code == 401
    assert api_client.get("/api/campaigns").status_code == 401
