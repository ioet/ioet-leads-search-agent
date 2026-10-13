"""Fetch ioet skills catalog from the skills microservice."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_URL = "http://localhost:8003"


class SkillsCatalogError(RuntimeError):
    pass


def skills_service_base() -> str:
    return os.environ.get("SKILLS_SERVICE_URL", DEFAULT_SKILLS_URL).rstrip("/")


def catalog_timeout_seconds() -> float:
    # Must stay below the LittleHorse task timeout (TASK_TIMEOUT_SECONDS, 120 in prod).
    return float(os.environ.get("SKILLS_CATALOG_TIMEOUT_SECONDS", "160"))


def fetch_skills_catalog(session: requests.Session | None = None) -> list[dict[str, Any]]:
    url = f"{skills_service_base()}/v1/catalog"
    http = session or requests.Session()
    response = http.get(url, timeout=catalog_timeout_seconds())
    if not response.ok:
        logger.error("Skills catalog failed: %s %s", response.status_code, response.text[:500])
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise SkillsCatalogError(f"Expected list from skills catalog, got {type(data)!r}")
    return data
