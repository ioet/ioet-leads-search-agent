"""Slack notify client tests (HTTP mocked)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.common.schemas import NotifyRequest
from services.notify.client import SlackClient, format_failure_text
from tests.helpers import assert_http_call_json, assert_model


def test_notify_posts_message_as_is(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    session.post.return_value = response

    request = NotifyRequest(
        message="Leads campaign `c1` (dry-run): 2 published.",
        details={"kind": "campaign_summary", "campaign_id": "c1"},
    )
    client = SlackClient(session=session)
    result = client.notify(request)
    assert isinstance(result, dict)
    assert result["status"] == "sent"

    payload = assert_http_call_json(session, expected={"text": request.message})
    assert isinstance(payload["text"], str)
    args, kwargs = session.post.call_args
    assert args[0].startswith("https://hooks.slack.com/")


def test_notify_endpoint(monkeypatch) -> None:
    from services.notify.app import app

    mock_client = MagicMock()
    mock_client.notify.return_value = {"status": "sent"}
    monkeypatch.setattr("services.notify.handler._client", lambda: mock_client)

    client = TestClient(app)
    request_body = {
        "message": ":mag: No companies found for campaign `demo-001`.",
        "details": {"kind": "empty_search"},
    }
    assert_model(request_body, NotifyRequest)
    response = client.post("/v1/notify", json=request_body)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
    assert response.json()["status"] == "sent"

    mock_client.notify.assert_called_once()
    sent = mock_client.notify.call_args[0][0]
    assert isinstance(sent, NotifyRequest)
    assert sent.message == request_body["message"]
    assert sent.details == request_body["details"]


def test_notify_endpoints_require_webhook(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    from services.notify.app import app

    client = TestClient(app)
    assert (
        client.post("/v1/notify", json={"message": "hello"}).status_code == 503
    )
    assert client.post("/v1/failure", json={"campaign_id": "c1", "error": "boom"}).status_code == 503


def test_failure_posts_expected_slack_text(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    session.post.return_value = response

    client = SlackClient(session=session)
    payload = {
        "campaign_id": "demo-001",
        "wf_run_id": "demo-001",
        "step_name": "upsert-hubspot",
        "error": "ERROR",
        "lead": "Acme",
    }
    result = client.failure(payload)
    assert result["status"] == "sent"
    slack_payload = assert_http_call_json(session)
    assert slack_payload["text"].startswith(":warning: Error on `upsert-hubspot`")
    assert "campaign `demo-001`" in slack_payload["text"]
    assert "Leads workflow failure" not in slack_payload["text"]
    assert "Acme" in slack_payload["text"]


def test_format_failure_text_uses_step_and_wf_run() -> None:
    text = format_failure_text(
        {
            "step_name": "fetch-ioet-skills-catalog",
            "wf_run_id": "29a63925f56b4f56844f6680b2dd18eb",
            "error": "ERROR",
        }
    )
    assert text == (
        ":warning: Error on `fetch-ioet-skills-catalog` — "
        "campaign `29a63925f56b4f56844f6680b2dd18eb`"
    )


def test_notify_collapses_multiline_text(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    session.post.return_value = response

    request = NotifyRequest(
        message='id: "abc"\nparent_wf_run_id {\n  id: "def"\n}',
    )
    SlackClient(session=session).notify(request)
    payload = assert_http_call_json(session)
    assert "\n" not in payload["text"]
    assert 'id: "abc"' in payload["text"]


def test_notify_endpoint_maps_slack_http_error(monkeypatch) -> None:
    import requests
    from services.notify.app import app

    mock_client = MagicMock()
    mock_client.notify.side_effect = requests.HTTPError("webhook failed")
    monkeypatch.setattr("services.notify.handler._client", lambda: mock_client)

    client = TestClient(app)
    response = client.post("/v1/notify", json={"message": "hello"})
    assert response.status_code == 502
