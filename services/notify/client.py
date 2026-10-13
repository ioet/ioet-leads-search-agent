"""Slack notification client (incoming webhook)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from services.common.schemas import NotifyRequest

logger = logging.getLogger(__name__)

_SLACK_TEXT_LIMIT = 3500


def _sanitize_slack_text(text: str, *, limit: int = _SLACK_TEXT_LIMIT) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = cleaned.replace("```", "`")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned


def format_failure_text(payload: dict[str, Any]) -> str:
    """Slack text for a step error (not a whole-workflow failure)."""
    step = str(payload.get("step_name") or payload.get("step") or "").strip()
    campaign = str(
        payload.get("wf_run_id") or payload.get("campaign_id") or "unknown"
    ).strip() or "unknown"
    error = str(payload.get("error") or payload.get("message") or "").strip()
    if not step and error and ":" in error:
        step = error.split(":", 1)[0].strip()
    if not step:
        step = "unknown-step"

    text = f":warning: Error on `{step}` — campaign `{campaign}`"
    if error and error.upper() != "ERROR":
        if error not in {step, f"{step}: ERROR", f"{step}:ERROR"} and not error.startswith(
            f"{step}:"
        ):
            text += f": {error}"
    lead = payload.get("lead") or payload.get("company") or ""
    if lead:
        text += f" (lead `{lead}`)"
    return text


class SlackConfigError(RuntimeError):
    pass


class SlackClient:
    def __init__(self, webhook_url: str | None = None, session: requests.Session | None = None) -> None:
        self.webhook_url = (
            webhook_url if webhook_url is not None else os.environ.get("SLACK_WEBHOOK_URL", "")
        ).strip()
        self.session = session or requests.Session()

    def post_message(self, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, str]:
        if not self.webhook_url:
            raise SlackConfigError("SLACK_WEBHOOK_URL is not configured")
        payload: dict[str, Any] = {"text": _sanitize_slack_text(text)}
        if blocks:
            payload["blocks"] = blocks
        response = self.session.post(self.webhook_url, json=payload, timeout=30)
        if not response.ok:
            logger.error("Slack webhook failed: %s %s", response.status_code, response.text[:500])
            response.raise_for_status()
        return {"status": "sent"}

    def notify(self, request: NotifyRequest) -> dict[str, str]:
        """Post a pre-formatted message to Slack."""
        return self.post_message(request.message)

    def failure(self, payload: dict[str, Any]) -> dict[str, str]:
        return self.post_message(format_failure_text(payload))
