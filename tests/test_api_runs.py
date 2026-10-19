"""Campaign run start + internal callback tests."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest_api import make_api_client, sample_icp_dict, signup_verify_login


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_INTERNAL_SERVICE_TOKEN", "test-internal-token")
    yield from make_api_client()


def _seed_campaign(client: TestClient, capsys: pytest.CaptureFixture[str]) -> dict:
    signup_verify_login(client, capsys=capsys)
    icp = client.post(
        "/api/icps",
        json={"title": "Test ICP", "icp": sample_icp_dict()},
    ).json()
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "Demo campaign",
            "icp_id": icp["icp_id"],
            "status": "active",
            "config": {"run_mode": "dry_run", "companies_per_run": 5},
        },
    ).json()
    return campaign


def test_start_run_calls_littlehorse(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_campaign(api_client, capsys)

    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-abc",
    ) as mocked:
        resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["lh_wf_run_id"] == "wf-abc"
    mocked.assert_called_once()
    variables = mocked.call_args.args[0]
    assert variables["campaign-id"] == campaign["campaign_id"]
    assert variables["run-id"] == body["run_id"]
    assert variables["dry-run"] is True
    assert variables["max-leads"] == 5
    assert "primary" in variables["segment-ids"]
    assert variables["icp-ref"].startswith("local://")
    assert isinstance(variables["campaign-config"], dict)


def test_start_run_marks_failed_when_lh_errors(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from services.api.lh_client import LittleHorseError

    campaign = _seed_campaign(api_client, capsys)
    with patch(
        "services.api.run_starter.start_leads_search_run",
        side_effect=LittleHorseError("connection refused"),
    ):
        resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        )
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed"
    assert "connection refused" in (resp.json().get("result_summary") or {}).get(
        "error", ""
    )


def test_internal_complete_run(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_campaign(api_client, capsys)
    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-abc",
    ):
        run = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        ).json()

    denied = api_client.post(
        f"/api/internal/runs/{run['run_id']}/complete",
        json={"status": "completed", "result_summary": {"ok": True}},
    )
    assert denied.status_code == 401

    done = api_client.post(
        f"/api/internal/runs/{run['run_id']}/complete",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "status": "completed",
            "result_summary": {"message": "done", "details": {"leads_published": 2}},
            "lh_wf_run_id": "wf-abc",
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["ended_at"]
    assert done.json()["result_summary"]["details"]["leads_published"] == 2

    listed = api_client.get(f"/api/campaigns/{campaign['campaign_id']}")
    assert listed.status_code == 200
    assert listed.json()["companies_upserted"] == 2

    again = api_client.post(
        f"/api/internal/runs/{run['run_id']}/complete",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "status": "completed",
            "result_summary": {"message": "done", "details": {"leads_published": 2}},
        },
    )
    assert again.status_code == 200
    listed = api_client.get(f"/api/campaigns/{campaign['campaign_id']}")
    assert listed.json()["companies_upserted"] == 2


def test_internal_campaign_name(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_campaign(api_client, capsys)
    denied = api_client.get(f"/api/internal/campaigns/{campaign['campaign_id']}")
    assert denied.status_code == 401
    named = api_client.get(
        f"/api/internal/campaigns/{campaign['campaign_id']}",
        headers={"X-Internal-Token": "test-internal-token"},
    )
    assert named.status_code == 200, named.text
    assert named.json()["name"] == "Demo campaign"


def test_review_mode_skips_hubspot_writes(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    signup_verify_login(api_client, capsys=capsys)
    icp = api_client.post(
        "/api/icps",
        json={"title": "Test ICP", "icp": sample_icp_dict()},
    ).json()
    campaign = api_client.post(
        "/api/campaigns",
        json={
            "name": "Review campaign",
            "icp_id": icp["icp_id"],
            "status": "active",
            "config": {"run_mode": "review", "companies_per_run": 4, "email_owner": True},
        },
    ).json()
    assert campaign["config"]["run_mode"] == "review"
    assert campaign["config"]["email_owner"] is True

    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-review",
    ) as mocked:
        resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        )
    assert resp.status_code == 201, resp.text
    variables = mocked.call_args.args[0]
    assert variables["dry-run"] is True
    assert variables["campaign-config"]["run_mode"] == "review"


def test_record_campaign_run_task_skips_empty_run_id() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import record_campaign_run_task

    ctx = MagicMock()
    ctx.wf_run_id = "wf-1"
    result = asyncio.run(record_campaign_run_task("", {"message": "x"}, "completed", ctx))
    assert result == "skipped"


def test_record_campaign_run_task_posts(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import record_campaign_run_task

    monkeypatch.setenv("API_INTERNAL_SERVICE_TOKEN", "test-internal-token")
    monkeypatch.setenv("CAMPAIGN_API_BASE_URL", "http://testserver")

    campaign = _seed_campaign(api_client, capsys)
    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-abc",
    ):
        run = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/runs",
            json={"trigger": "manual"},
        ).json()

    # Point the worker HTTP call at the TestClient transport.
    import requests

    class _SessionAdapter(requests.Session):
        def request(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
            path = url.split("http://testserver", 1)[-1]
            headers = kwargs.get("headers") or {}
            json_body = kwargs.get("json")
            if method.upper() == "POST":
                return _Resp(
                    api_client.post(path, headers=headers, json=json_body)
                )
            raise AssertionError(method)

    class _Resp:
        def __init__(self, response) -> None:  # type: ignore[no-untyped-def]
            self._response = response
            self.ok = response.status_code < 400
            self.status_code = response.status_code
            self.text = response.text
            self.reason = response.reason_phrase

        def json(self):  # type: ignore[no-untyped-def]
            return self._response.json()

    def fake_post(url, json=None, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        path = url.split("http://testserver", 1)[-1]
        return _Resp(api_client.post(path, headers=headers or {}, json=json))

    monkeypatch.setattr("requests.post", fake_post)

    ctx = MagicMock()
    ctx.wf_run_id = "wf-abc"
    result = asyncio.run(
        record_campaign_run_task(
            run["run_id"],
            {"message": "summary", "details": {"kind": "campaign_summary"}},
            "completed",
            ctx,
        )
    )
    assert result == "recorded"
    got = api_client.get(f"/api/runs/{run['run_id']}")
    assert got.json()["status"] == "completed"


def test_unsaved_test_run_is_dry_and_does_not_persist(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    signup_verify_login(api_client, capsys=capsys)
    icp = api_client.post(
        "/api/icps",
        json={"title": "Test ICP", "icp": sample_icp_dict()},
    ).json()

    with (
        patch(
            "services.api.run_starter.start_leads_search_run",
            return_value="wf-test",
        ) as mocked,
        patch(
            "services.api.stores.campaign_runs.create_run",
            side_effect=AssertionError("test run must not write a run row"),
        ),
    ):
        resp = api_client.post(
            "/api/campaigns/test-run",
            json={
                "name": "Scratch",
                "icp_id": icp["icp_id"],
                "config": {"run_mode": "live", "companies_per_run": 3},
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lh_wf_run_id"] == "wf-test"
    assert body["dry_run"] is True
    assert body["companies_per_run"] == 3
    variables = mocked.call_args.args[0]
    assert variables["dry-run"] is True
    assert variables["run-id"] == ""
    assert variables["campaign-id"] == "unsaved-test"
    assert variables["max-leads"] == 3
    assert variables["campaign-config"]["run_mode"] == "dry_run"
    assert api_client.get("/api/campaigns").json() == []
