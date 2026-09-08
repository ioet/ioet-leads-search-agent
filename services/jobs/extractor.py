"""Bedrock extraction of required skills from job descriptions."""

from __future__ import annotations

import json
import logging
from typing import Any

from services.agent.bedrock import BedrockClient, BedrockResponseError
from services.common.schemas import JobPosting

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "You extract technical and professional skills explicitly required in job descriptions. "
    "Return ONLY valid JSON — no markdown."
)


def extract_required_skills(
    postings: list[JobPosting],
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> list[str]:
    if not postings:
        return []

    client = bedrock or BedrockClient(model_id=model_id, complexity="low")
    payload = {
        "postings": [p.model_dump(exclude_none=True) for p in postings],
        "instructions": (
            "From the job descriptions, list distinct skills, tools, languages, and frameworks "
            "the employer requires or strongly prefers. Use concise canonical names "
            "(e.g. Python, React, AWS, Kubernetes). Omit soft skills unless explicitly required. "
            "Deduplicate case-insensitively."
        ),
        "output_schema": {"required_skills": ["string"]},
    }
    raw = client.converse_json(_EXTRACT_SYSTEM, json.dumps(payload, indent=2))
    return _parse_required_skills(raw)


def _parse_required_skills(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        raise BedrockResponseError(f"Skill extraction response must be object, got {type(raw)!r}")
    items = raw.get("required_skills")
    if not isinstance(items, list):
        return []

    seen: set[str] = set()
    skills: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(text)
    return skills
