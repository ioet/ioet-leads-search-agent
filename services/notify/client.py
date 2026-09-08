"""Slack notification client (incoming webhook)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from services.common.schemas import NotifyRequest

logger = logging.getLogger(__name__)


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
        payload: dict[str, Any] = {"text": text}
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
        campaign = payload.get("campaign_id") or "unknown"
        error = payload.get("error") or payload.get("message") or str(payload)
        lead = payload.get("lead") or payload.get("company") or ""
        text = f":warning: Leads workflow failure — campaign `{campaign}`"
        if lead:
            text += f" lead `{lead}`"
        text += f": {error}"
        return self.post_message(text)
