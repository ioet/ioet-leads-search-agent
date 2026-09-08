"""AWS Bedrock Converse API client (HTTP + API key, same pattern as birthday_slack_bot)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

import requests

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

Complexity = Literal["high", "low"]

# High: ICP scoring, outreach drafting. Low: skill extraction, catalog matching.
# Google Gemma 3 — high/low split (27B ~ scoring/outreach, 4B ~ skills extract/match).
DEFAULT_MODEL_HIGH = "google.gemma-3-27b-it"
DEFAULT_MODEL_LOW = "google.gemma-3-4b-it"


class BedrockConfigError(RuntimeError):
    pass


class BedrockResponseError(RuntimeError):
    pass


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def converse_url(model_id: str, region: str) -> str:
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"


def resolve_model_id(
    model_id: str | None = None,
    *,
    complexity: Complexity = "high",
) -> str:
    """Prefer an explicit request override, then complexity env, then code defaults."""
    explicit = (model_id or "").strip()
    if explicit:
        return explicit
    if complexity == "high":
        return (
            _env("AWS_BEDROCK_MODEL_ID_HIGH")
            or _env("AWS_BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID")
            or DEFAULT_MODEL_HIGH
        )
    return (
        _env("AWS_BEDROCK_MODEL_ID_LOW")
        or _env("AWS_BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID")
        or DEFAULT_MODEL_LOW
    )


class BedrockClient:
    """Calls Bedrock Converse over HTTPS with ``Authorization: Bearer <API key>``."""

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        region: str | None = None,
        session: requests.Session | None = None,
        *,
        complexity: Complexity = "high",
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else _env("AWS_BEDROCK_API_KEY")
        ).strip()
        self.model_id = resolve_model_id(model_id, complexity=complexity)
        self.complexity = complexity
        self.region = (
            region
            if region is not None
            else _env("AWS_BEDROCK_REGION", "AWS_REGION", default="us-east-1")
        ).strip()
        self._session = session or requests.Session()

    def converse_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Any:
        """Call Bedrock Converse and parse a JSON object/array from the reply."""
        text = self.converse_text(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return parse_json_from_text(text)

    def converse_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        if not self.api_key:
            raise BedrockConfigError("AWS_BEDROCK_API_KEY is not configured")
        if not self.model_id:
            raise BedrockConfigError(
                "Bedrock model ID is not configured "
                "(set model_id on the request, or AWS_BEDROCK_MODEL_ID_HIGH / AWS_BEDROCK_MODEL_ID_LOW)"
            )

        url = converse_url(self.model_id, self.region)
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user}],
                }
            ],
            "system": [{"text": system}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.info(
            "Bedrock converse model=%s region=%s max_tokens=%d",
            self.model_id,
            self.region,
            max_tokens,
        )
        response = self._session.post(url, json=payload, headers=headers, timeout=120)
        if not response.ok:
            logger.error(
                "Bedrock request failed: %s %s",
                response.status_code,
                response.text[:500],
            )
            raise BedrockResponseError(
                f"Bedrock request failed ({response.status_code}): {response.text[:500]}"
            )
        return extract_text(response.json())


def extract_text(response_body: dict[str, Any]) -> str:
    content = response_body.get("output", {}).get("message", {}).get("content", [])
    text_parts = [block.get("text", "") for block in content if block.get("text")]
    message = "\n".join(part.strip() for part in text_parts if part.strip())
    if not message:
        raise BedrockResponseError("Bedrock returned an empty message")
    return message


def parse_json_from_text(text: str) -> Any:
    """Extract JSON from raw model text (plain JSON or fenced code block)."""
    stripped = text.strip()
    match = _JSON_BLOCK_RE.search(stripped)
    candidate = match.group(1).strip() if match else stripped
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        for opener, closer in (("{", "}"), ("[", "]")):
            start = candidate.find(opener)
            end = candidate.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise BedrockResponseError(f"Could not parse JSON from model output: {text[:500]!r}")
