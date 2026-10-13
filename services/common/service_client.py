"""HTTP client helpers used by LittleHorse task workers."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def service_url(task_name: str) -> str:
    """Resolve base URL for a task from ``SERVICE_URL_<TASK>`` env vars."""
    env_key = f"SERVICE_URL_{task_name.upper().replace('-', '_')}"
    url = os.environ.get(env_key, "").strip()
    if not url:
        raise RuntimeError(
            f"Missing service URL for task {task_name!r}; set {env_key} in the environment"
        )
    return url.rstrip("/")


async def post_json(task_name: str, path: str, payload: Any) -> Any:
    base = service_url(task_name)
    url = f"{base}{path}"
    logger.info("POST %s payload=%s", url, payload)

    def _post() -> requests.Response:
        return requests.post(url, json=payload, timeout=300)

    response = await asyncio.to_thread(_post)
    if not response.ok:
        snippet = (response.text or response.reason or "").strip()
        snippet = " ".join(snippet.split())[:400]
        logger.error("%s failed: %s %s", task_name, response.status_code, snippet)
        raise RuntimeError(
            f"{task_name} HTTP {response.status_code}"
            + (f": {snippet}" if snippet else "")
        )
    result = response.json()
    if isinstance(result, dict):
        logger.info("%s response keys: %s", task_name, list(result.keys()))
    else:
        logger.info(
            "%s response type=%s size=%s",
            task_name,
            type(result).__name__,
            len(result) if hasattr(result, "__len__") else "?",
        )
    return result
