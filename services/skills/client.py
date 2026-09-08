"""BambooHR skills catalog client with short TTL cache."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = int(os.environ.get("BAMBOOHR_CACHE_TTL_SECONDS", "300"))


class BambooHRConfigError(RuntimeError):
    pass


class _CatalogCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at = 0.0
        self._items: list[dict[str, Any]] = []

    def get(self) -> list[dict[str, Any]] | None:
        with self._lock:
            if time.monotonic() < self._expires_at:
                return list(self._items)
            return None

    def set(self, items: list[dict[str, Any]], ttl_seconds: int) -> None:
        with self._lock:
            self._items = list(items)
            self._expires_at = time.monotonic() + ttl_seconds

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._expires_at = 0.0


_CACHE = _CatalogCache()


class BambooHRClient:
    """Live BambooHR directory + skill field pull (allowlisted fields only)."""

    def __init__(
        self,
        api_key: str | None = None,
        subdomain: str | None = None,
        skills_field: str | None = None,
        session: requests.Session | None = None,
        cache_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("BAMBOOHR_API_KEY", "")).strip()
        self.subdomain = (
            subdomain if subdomain is not None else os.environ.get("BAMBOOHR_SUBDOMAIN", "")
        ).strip()
        self.skills_field = (
            skills_field
            if skills_field is not None
            else os.environ.get("BAMBOOHR_SKILLS_FIELD", "skills")
        ).strip() or "skills"
        self.session = session or requests.Session()
        self.cache_ttl_seconds = cache_ttl_seconds

    def _ensure_config(self) -> None:
        if not self.api_key or not self.subdomain:
            raise BambooHRConfigError(
                "BAMBOOHR_API_KEY and BAMBOOHR_SUBDOMAIN must be configured"
            )

    def _base(self) -> str:
        return f"https://api.bamboohr.com/api/gateway.php/{self.subdomain}/v1"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._ensure_config()
        url = f"{self._base()}{path}"
        response = self.session.get(
            url,
            params=params,
            auth=(self.api_key, "x"),
            headers={"Accept": "application/json"},
            timeout=60,
        )
        if not response.ok:
            logger.error("BambooHR %s failed: %s %s", path, response.status_code, response.text[:500])
            response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def fetch_catalog(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = _CACHE.get()
            if cached is not None:
                return cached

        directory = self._get("/employees/directory")
        employees = directory.get("employees") or []
        fetch_details = os.environ.get("BAMBOOHR_FETCH_DETAILS", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        normalized: list[dict[str, Any]] = []
        for emp in employees:
            emp_id = str(emp.get("id") or "").strip()
            if not emp_id:
                continue
            skills = _parse_skills(emp.get(self.skills_field))
            detail: dict[str, Any] = {}
            # Prefer directory row; only hit per-employee endpoint when skills missing.
            if fetch_details and not skills:
                detail = self._employee_detail(emp_id)
                skills = _parse_skills(detail.get(self.skills_field))
            display_name = (
                emp.get("displayName")
                or " ".join(
                    p for p in [emp.get("firstName"), emp.get("lastName")] if p
                ).strip()
                or f"employee-{emp_id}"
            )
            # Explicit allowlist — never copy email/phone/SSN/salary from BambooHR.
            normalized.append(
                {
                    "employee_id": emp_id,
                    "display_name": str(display_name),
                    "job_title": _optional_str(emp.get("jobTitle") or detail.get("jobTitle")),
                    "department": _optional_str(emp.get("department") or detail.get("department")),
                    "skills": skills,
                }
            )

        _CACHE.set(normalized, self.cache_ttl_seconds)
        return normalized

    def lookup(self, skills: list[str], *, use_cache: bool = True) -> list[dict[str, Any]]:
        wanted = {s.strip().lower() for s in skills if s and s.strip()}
        if not wanted:
            return []
        catalog = self.fetch_catalog(use_cache=use_cache)
        matches: list[dict[str, Any]] = []
        for employee in catalog:
            emp_skills = employee.get("skills") or []
            if any(skill.lower() in wanted for skill in emp_skills):
                # Prefer overlapping skills in response order.
                overlap = [s for s in emp_skills if s.lower() in wanted]
                matches.append({**employee, "skills": overlap or emp_skills})
        return matches

    def _employee_detail(self, employee_id: str) -> dict[str, Any]:
        fields = f"jobTitle,department,{self.skills_field}"
        try:
            data = self._get(f"/employees/{employee_id}", params={"fields": fields, "onlyCurrent": "true"})
            return data if isinstance(data, dict) else {}
        except requests.HTTPError:
            logger.warning("BambooHR employee detail failed for %s; using directory row only", employee_id)
            return {}


def clear_catalog_cache() -> None:
    _CACHE.clear()


def _parse_skills(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    # BambooHR multi-lists often come as comma- or semicolon-separated.
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
