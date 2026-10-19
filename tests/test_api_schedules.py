"""Schedule sync + fire endpoint tests."""

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


def _seed_active_campaign(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> dict:
    signup_verify_login(client, capsys=capsys)
    icp = client.post(
        "/api/icps",
        json={"title": "Sched ICP", "icp": sample_icp_dict()},
    ).json()
    return client.post(
        "/api/campaigns",
        json={
            "name": "Scheduled campaign",
            "icp_id": icp["icp_id"],
            "status": "active",
            "config": {"run_mode": "dry_run", "companies_per_run": 3},
        },
    ).json()


def test_create_schedule_registers_lh(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-sched-abc",
    ) as schedule_fn, patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 7 * * 1",
                "timezone": "UTC",
                "enabled": True,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lh_schedule_id"] == "lh-sched-abc"
    assert body["enabled"] is True
    schedule_fn.assert_called_once()
    assert schedule_fn.call_args.kwargs["cron_expression"] == "0 7 * * 1"
    assert schedule_fn.call_args.kwargs["schedule_id"] == body["schedule_id"]


def test_create_schedule_rolls_back_on_lh_failure(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from services.api.lh_client import LittleHorseError

    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        side_effect=LittleHorseError("no lh"),
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        resp = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 7 * * 1",
                "timezone": "UTC",
                "enabled": True,
            },
        )

    assert resp.status_code == 502
    listed = api_client.get(f"/api/campaigns/{campaign['campaign_id']}/schedules")
    assert listed.json() == []


def test_disable_schedule_deletes_lh(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-sched-1",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ) as delete_fn:
        created = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 8 * * 2",
                "timezone": "UTC",
                "enabled": True,
            },
        ).json()

        patched = api_client.patch(
            f"/api/schedules/{created['schedule_id']}",
            json={"enabled": False},
        )

    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["lh_schedule_id"] is None
    delete_fn.assert_called()


def test_ending_campaign_disables_schedules(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-sched-end",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ) as delete_fn:
        api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 9 * * 3",
                "timezone": "UTC",
                "enabled": True,
            },
        )
        ended = api_client.patch(
            f"/api/campaigns/{campaign['campaign_id']}",
            json={"status": "ended"},
        )

    assert ended.status_code == 200
    delete_fn.assert_called()
    schedules = api_client.get(f"/api/campaigns/{campaign['campaign_id']}/schedules")
    assert schedules.status_code == 200
    assert all(row["enabled"] is False for row in schedules.json())
    assert all(row["lh_schedule_id"] is None for row in schedules.json())


def test_fire_schedule_starts_run_and_disables_once(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-once-1",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        schedule = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "once",
                "expression": "2026-12-01T15:00:00Z",
                "timezone": "UTC",
                "enabled": True,
            },
        ).json()

    with patch(
        "services.api.run_starter.start_leads_search_run",
        return_value="wf-from-schedule",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        fire = api_client.post(
            f"/api/internal/schedules/{schedule['schedule_id']}/fire",
            headers={"X-Internal-Token": "test-internal-token"},
        )

    assert fire.status_code == 200, fire.text
    body = fire.json()
    assert body["trigger"] == "scheduled"
    assert body["lh_wf_run_id"] == "wf-from-schedule"
    assert body["status"] == "running"

    refreshed = api_client.get(
        f"/api/campaigns/{campaign['campaign_id']}/schedules",
    ).json()
    assert len(refreshed) == 1
    assert refreshed[0]["enabled"] is False
    assert refreshed[0]["lh_schedule_id"] is None


def test_fire_rejects_ended_campaign(
    api_client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from services.api.stores import campaigns as campaign_store
    from services.api.stores import schedules as schedule_store
    from services.api.schemas.entities import CampaignStatus

    campaign = _seed_active_campaign(api_client, capsys)

    with patch(
        "services.api.schedule_sync.schedule_fire_campaign",
        return_value="lh-x",
    ), patch(
        "services.api.schedule_sync.delete_scheduled_wf_run",
    ):
        schedule = api_client.post(
            f"/api/campaigns/{campaign['campaign_id']}/schedules",
            json={
                "type": "recurring",
                "expression": "0 10 * * 4",
                "timezone": "UTC",
                "enabled": True,
            },
        ).json()

    # Simulate a race: campaign ended in DB while LH cron still has the schedule enabled.
    campaign_store.update_campaign(campaign["campaign_id"], status=CampaignStatus.ENDED)
    schedule_store.update_schedule(schedule["schedule_id"], enabled=True)

    with patch("services.api.schedule_sync.delete_scheduled_wf_run"):
        fire = api_client.post(
            f"/api/internal/schedules/{schedule['schedule_id']}/fire",
            headers={"X-Internal-Token": "test-internal-token"},
        )
    assert fire.status_code == 400
    assert "ended" in fire.json()["detail"].lower()
