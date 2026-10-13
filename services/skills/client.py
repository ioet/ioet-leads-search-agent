"""BambooHR skills catalog client with short TTL cache."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from services.skills.skill_fields import (
    chunked,
    skill_field_aliases,
    skills_from_level_fields,
)

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = int(os.environ.get("BAMBOOHR_CACHE_TTL_SECONDS", "300"))
# Prefer one request when possible (matches working Bamboo curl). Chunk only if huge.
_SKILL_FIELD_CHUNK = int(os.environ.get("BAMBOOHR_SKILL_FIELD_CHUNK", "200"))
# One detail GET per employee; sequential calls take ~90s for the full directory,
# which exceeds the worker's catalog timeout.
_DETAIL_CONCURRENCY = int(os.environ.get("BAMBOOHR_DETAIL_CONCURRENCY", "8"))
_RETRY_STATUSES = frozenset({429, 503})
_MAX_ATTEMPTS = 3


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
    """Live BambooHR directory + per-skill custom fields (levels 1–5)."""

    def __init__(
        self,
        api_key: str | None = None,
        subdomain: str | None = None,
        skills_field: str | None = None,
        session: requests.Session | None = None,
        cache_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        skill_fields: list[str] | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("BAMBOOHR_API_KEY", "")).strip()
        self.subdomain = (
            subdomain if subdomain is not None else os.environ.get("BAMBOOHR_SUBDOMAIN", "")
        ).strip()
        # Legacy single multilist / text field (optional fallback).
        self.skills_field = (
            skills_field
            if skills_field is not None
            else os.environ.get("BAMBOOHR_SKILLS_FIELD", "skills")
        ).strip() or "skills"
        self.skill_fields = list(skill_fields) if skill_fields is not None else skill_field_aliases()
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
        # Bamboo `fields=a,b,c` must keep literal commas (same as curl).
        # requests' default encoding turns commas into %2C; Bamboo then ignores
        # the list and returns only {"id": "..."}.
        request_params = params
        if params and "fields" in params:
            fields = str(params["fields"])
            other = {k: v for k, v in params.items() if k != "fields"}
            from urllib.parse import urlencode

            extra = urlencode(other)
            url = f"{url}?fields={fields}" + (f"&{extra}" if extra else "")
            request_params = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = self.session.get(
                url,
                params=request_params,
                auth=(self.api_key, "x"),
                headers={"Accept": "application/json"},
                timeout=60,
            )
            if response.status_code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS:
                break
            time.sleep(_retry_after_seconds(response, attempt))
        if not response.ok:
            logger.error("BambooHR %s failed: %s %s", path, response.status_code, response.text[:500])
            response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def list_skill_related_fields(self) -> list[dict[str, Any]]:
        """Return Bamboo meta/fields entries whose name/alias looks skill-related."""
        raw = self._get("/meta/fields")
        fields = raw if isinstance(raw, list) else []
        out: list[dict[str, Any]] = []
        for item in fields:
            if not isinstance(item, dict):
                continue
            blob = f"{item.get('name', '')} {item.get('alias', '')} {item.get('id', '')}".lower()
            if any(token in blob for token in ("skill", "competenc", "expertise", "tech stack", "technology")):
                out.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "alias": item.get("alias"),
                        "type": item.get("type"),
                    }
                )
        return out

    def probe_skills_field(self, employee_id: str | None = None) -> dict[str, Any]:
        """One-employee probe for level-based custom skill fields (ops / debugging)."""
        directory = self._get("/employees/directory")
        employees = directory.get("employees") or []
        if not employees:
            return {"error": "directory empty"}
        emp = next(
            (e for e in employees if employee_id and str(e.get("id")) == str(employee_id)),
            employees[0],
        )
        emp_id = str(emp.get("id"))
        detail = self._employee_detail(emp_id)
        level_skills = skills_from_level_fields(detail, self.skill_fields)
        return {
            "employee_id": emp_id,
            "display_name": emp.get("displayName"),
            "skill_field_count": len(self.skill_fields),
            "legacy_skills_field": self.skills_field,
            "directory_has_legacy_field": self.skills_field in emp,
            "detail_key_count": len(detail.keys()) if detail else 0,
            "detail_sample_keys": sorted(detail.keys())[:40] if detail else [],
            "parsed_skills": level_skills,
            "parsed_skills_count": len(level_skills),
            "hint": (
                "ioet Bamboo stores one custom field per skill with levels 1–5 "
                "(e.g. customAWS=4). Set BAMBOOHR_SKILL_FIELDS to override the default allowlist. "
                "fields= must use literal commas (not %2C)."
            ),
        }

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

        employee_ids = [str(emp.get("id") or "").strip() for emp in employees]
        details: dict[str, dict[str, Any]] = {}
        if fetch_details:
            details = self._employee_details([emp_id for emp_id in employee_ids if emp_id])

        detail_failures = 0
        normalized: list[dict[str, Any]] = []
        for emp, emp_id in zip(employees, employee_ids):
            if not emp_id:
                continue

            # Legacy: single multilist/text field sometimes present on directory.
            skills = _parse_skills(emp.get(self.skills_field))
            detail: dict[str, Any] = {}

            if fetch_details:
                detail = details.get(emp_id) or {}
                if not detail:
                    detail_failures += 1
                else:
                    level_skills = skills_from_level_fields(detail, self.skill_fields)
                    if level_skills:
                        skills = level_skills
                    elif not skills:
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

        with_skills = sum(1 for row in normalized if row.get("skills"))
        if normalized and with_skills == 0:
            logger.warning(
                "Bamboo catalog has 0/%d employees with skills "
                "(level_fields=%d, legacy_field=%r, detail_failures=%d). "
                "Check BAMBOOHR_SKILL_FIELDS allowlist and API field permissions.",
                len(normalized),
                len(self.skill_fields),
                self.skills_field,
                detail_failures,
            )
        else:
            logger.info(
                "Bamboo catalog: %d/%d employees with skills (%d level fields configured)",
                with_skills,
                len(normalized),
                len(self.skill_fields),
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
                overlap = [s for s in emp_skills if s.lower() in wanted]
                matches.append({**employee, "skills": overlap or emp_skills})
        return matches

    def _employee_details(self, employee_ids: list[str]) -> dict[str, dict[str, Any]]:
        workers = max(1, min(_DETAIL_CONCURRENCY, len(employee_ids)))
        if workers == 1:
            return {emp_id: self._employee_detail(emp_id) for emp_id in employee_ids}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(zip(employee_ids, pool.map(self._employee_detail, employee_ids)))

    def _employee_detail(self, employee_id: str) -> dict[str, Any]:
        """Fetch job fields + skill custom fields; merge into one dict.

        Matches the working Bamboo pattern: one (or few) GET(s) with explicit
        `fields=` and no `onlyCurrent` (that param caused empty custom fields).
        """
        aliases = list(self.skill_fields)
        if self.skills_field and self.skills_field not in aliases:
            aliases = [self.skills_field, *aliases]

        # jobTitle/department first, then skill aliases in chunks if needed.
        base = ["jobTitle", "department"]
        groups = [base + aliases] if len(aliases) <= _SKILL_FIELD_CHUNK else [
            base,
            *chunked(aliases, _SKILL_FIELD_CHUNK),
        ]

        merged: dict[str, Any] = {}
        for group in groups:
            fields = ",".join(group)
            try:
                data = self._get(
                    f"/employees/{employee_id}",
                    params={"fields": fields},
                )
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", "?")
                body = ""
                if getattr(exc, "response", None) is not None:
                    body = (exc.response.text or "")[:200]
                logger.warning(
                    "BambooHR employee detail failed for %s (fields=%d status=%s): %s",
                    employee_id,
                    len(group),
                    status,
                    body or exc,
                )
                continue
            if isinstance(data, dict):
                merged.update(data)

        return merged


def clear_catalog_cache() -> None:
    _CACHE.clear()


def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
    raw = response.headers.get("Retry-After") if response.headers else None
    try:
        return min(float(raw), 10.0) if raw else float(attempt)
    except (TypeError, ValueError):
        return float(attempt)


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
