"""Persist HubSpot mock CRM data to the local filesystem for easy inspection."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def output_dir() -> Path:
    raw = os.environ.get("HUBSPOT_MOCK_OUTPUT_DIR", ".cache/hubspot-mock").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    (path / "leads").mkdir(parents=True, exist_ok=True)
    return path


def slug_from_company(company: dict[str, Any]) -> str:
    domain = str(company.get("domain") or "").strip()
    name = str(company.get("name") or "unknown").strip()
    raw = domain or name.lower().replace(" ", "-")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return slug or "unknown"


def persist_store(store: dict[str, Any]) -> Path:
    path = output_dir() / "store.json"
    path.write_text(json.dumps(store, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def persist_upsert(
    *,
    lead: dict[str, Any],
    payload: dict[str, Any],
    hubspot_ids: dict[str, str],
    dry_run: bool,
) -> Path:
    base = output_dir()
    slug = slug_from_company(lead.get("company") or {})
    upserted_at = datetime.now(UTC).isoformat()

    record: dict[str, Any] = {
        "upserted_at": upserted_at,
        "dry_run": dry_run,
        "company": lead.get("company"),
        "contacts": lead.get("contacts"),
        "skill_matches": lead.get("skill_matches"),
        "job_context": lead.get("job_context"),
        "notes": lead.get("notes"),
        "status": lead.get("status"),
        "hubspot_ids": hubspot_ids,
        "hubspot_payload": payload,
    }

    lead_path = base / "leads" / f"{slug}.json"
    lead_path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    note_body = payload.get("note")
    if note_body:
        note_path = base / "leads" / f"{slug}-note.txt"
        note_path.write_text(str(note_body).strip() + "\n", encoding="utf-8")

    history_path = base / "leads" / "history" / f"{upserted_at.replace(':', '-')}_{slug}.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    return lead_path
