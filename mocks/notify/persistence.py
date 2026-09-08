"""Persist notify mock Slack payloads to the local filesystem."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def output_dir() -> Path:
    raw = os.environ.get("NOTIFY_MOCK_OUTPUT_DIR", ".cache/notify-mock").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    (path / "history").mkdir(parents=True, exist_ok=True)
    return path


def format_slack_text(msg_type: str, payload: dict[str, Any]) -> str:
    """Format the text that would be posted to Slack."""
    if msg_type == "notify":
        return str(payload.get("message") or "").strip()

    campaign = payload.get("campaign_id") or "unknown"
    error = payload.get("error") or payload.get("message") or str(payload)
    lead = payload.get("lead") or payload.get("company") or ""
    text = f":warning: Leads workflow failure — campaign `{campaign}`"
    if lead:
        text += f" lead `{lead}`"
    text += f": {error}"
    return text


def persist_messages(messages: list[dict[str, Any]]) -> Path:
    path = output_dir() / "messages.json"
    path.write_text(json.dumps(messages, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def persist_message(msg_type: str, payload: dict[str, Any]) -> Path:
    base = output_dir()
    sent_at = datetime.now(UTC).isoformat()
    slack_text = format_slack_text(msg_type, payload)

    record = {
        "sent_at": sent_at,
        "type": msg_type,
        "slack_text": slack_text,
        "payload": payload,
    }

    latest_txt = base / f"latest-{msg_type}.txt"
    latest_txt.write_text(slack_text.strip() + "\n", encoding="utf-8")

    feed_path = base / "slack-feed.txt"
    separator = f"\n--- {sent_at} ({msg_type}) ---\n"
    with feed_path.open("a", encoding="utf-8") as feed:
        if feed_path.stat().st_size > 0:
            feed.write(separator)
        feed.write(slack_text.strip() + "\n")

    stamp = sent_at.replace(":", "-")
    history_json = base / "history" / f"{stamp}_{msg_type}.json"
    history_txt = base / "history" / f"{stamp}_{msg_type}.txt"
    history_json.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    history_txt.write_text(slack_text.strip() + "\n", encoding="utf-8")

    return latest_txt
