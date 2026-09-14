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
        """One-employee probe for the configured skills field (ops / debugging)."""
        directory = self._get("/employees/directory")
        employees = directory.get("employees") or []
        if not employees:
            return {"error": "directory empty"}
        emp = next((e for e in employees if employee_id and str(e.get("id")) == str(employee_id)), employees[0])
        emp_id = str(emp.get("id"))
        detail = self._employee_detail(emp_id)
        related = self.list_skill_related_fields()

        raw_meta = self._get("/meta/fields")
        meta_fields = raw_meta if isinstance(raw_meta, list) else []
        # Help ops find the real alias when it isn't named "*skill*".
        interesting: list[dict[str, Any]] = []
        for item in meta_fields:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            alias = str(item.get("alias") or "")
            ftype = str(item.get("type") or "").lower()
            blob = f"{name} {alias}".lower()
            if ftype in {"list", "multilist", "checkbox", "textarea", "text"} or any(
                token in blob
                for token in (
                    "skill",
                    "tech",
                    "stack",
                    "tool",
                    "compet",
                    "language",
                    "framework",
                    "expertise",
                    "capability",
                    "tag",
                )
            ):
                interesting.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "alias": item.get("alias"),
                        "type": item.get("type"),
                    }
                )

        return {
            "employee_id": emp_id,
            "display_name": emp.get("displayName"),
            "configured_skills_field": self.skills_field,
            "directory_has_configured_field": self.skills_field in emp,
            "directory_skills_raw": emp.get(self.skills_field),
            "detail_keys": sorted(detail.keys()) if detail else [],
            "detail_skills_raw": detail.get(self.skills_field) if detail else None,
            "detail_empty": not bool(detail),
            "parsed_skills": _parse_skills(detail.get(self.skills_field) if detail else emp.get(self.skills_field)),
            "skill_related_meta_fields": related,
            "meta_field_count": len(meta_fields),
            "candidate_meta_fields": interesting[:80],
            "hint": (
                "Directory never includes custom fields; skills come from GET /employees/{id}"
                " using BAMBOOHR_SKILLS_FIELD (must be the Bamboo field alias from meta/fields)."
                " detail_keys==['id'] usually means the requested field alias is invalid or not"
                " permitted for this API key."
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
        if employees and self.skills_field not in (employees[0] or {}):
            logger.info(
                "Bamboo directory has no %r field (normal for custom fields); "
                "will use per-employee detail when BAMBOOHR_FETCH_DETAILS is enabled",
                self.skills_field,
            )

        detail_failures = 0
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
                if not detail:
                    detail_failures += 1
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
            related = []
            try:
                related = self.list_skill_related_fields()
            except Exception:
                logger.exception("Could not list Bamboo meta fields while diagnosing empty skills")
            aliases = [str(f.get("alias") or f.get("id") or "") for f in related if f.get("alias") or f.get("id")]
            logger.warning(
                "Bamboo catalog has 0/%d employees with skills (field=%r, detail_failures=%d). "
                "Check BAMBOOHR_SKILLS_FIELD — skill-related meta aliases: %s",
                len(normalized),
                self.skills_field,
                detail_failures,
                aliases[:20] or "(none found)",
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
            if isinstance(data, dict) and self.skills_field not in data:
                logger.debug(
                    "Bamboo employee %s detail missing field %r (keys=%s)",
                    employee_id,
                    self.skills_field,
                    sorted(data.keys()),
                )
            return data if isinstance(data, dict) else {}
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", "?")
            body = ""
            if getattr(exc, "response", None) is not None:
                body = (exc.response.text or "")[:200]
            logger.warning(
                "BambooHR employee detail failed for %s (field=%r status=%s): %s",
                employee_id,
                self.skills_field,
                status,
                body or exc,
            )
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
