"""LittleHorse task workers — thin HTTP bridge to microservices (+ local helpers)."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import littlehorse
from littlehorse.config import LHConfig
from littlehorse.exceptions import LHTaskException
from littlehorse.worker import LHTaskWorker, WorkerContext

from services.common.catalog_store import (
    LATEST_CATALOG_REF,
    load_skills_catalog,
    require_skills_catalog,
    save_skills_catalog,
)
from services.common.limits import max_companies, max_contacts_per_company
from services.common.service_client import post_json
from services.agent.skills_source import fetch_skills_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tasks that POST to microservices (require SERVICE_URL_*).
HTTP_TASK_NAMES = [
    "search-companies",
    "score-companies-icp",
    "find-decision-makers",
    "sanitize-public-fields",
    "extract-job-skills",
    "match-ioet-skills",
    "draft-outreach-email",
    "upsert-hubspot",
    "notify",
    "notify-failure",
]

# Pure-local TaskDefs (no external HTTP).
LOCAL_TASK_NAMES = [
    "select-top-leads",
    "build-campaign-summary",
    "build-empty-search-notification",
    "count-companies",
    "fetch-ioet-skills-catalog",
]

TASK_NAMES = HTTP_TASK_NAMES + LOCAL_TASK_NAMES

_LH_ID_RE = re.compile(r'id:\s*"([^"]+)"')


def _lh_id(value: Any) -> str:
    """LittleHorse WfRunId as a short string (not the protobuf text dump)."""
    if value is None:
        return ""
    ident = getattr(value, "id", None)
    if isinstance(ident, str) and ident.strip():
        return ident.strip()
    text = str(value).strip()
    if not text:
        return ""
    match = _LH_ID_RE.search(text)
    if match:
        return match.group(1)
    if "\n" not in text and "{" not in text:
        return text
    return text.split("\n", 1)[0][:80]


def _task_guid(ctx: WorkerContext | None) -> str:
    if ctx is None:
        return ""
    try:
        return str(ctx.task_run_id.task_guid)
    except Exception:
        return str(getattr(ctx, "idempotency_key", "") or "")


def _raise_step_failed(ctx: WorkerContext | None, task_name: str, exc: BaseException) -> None:
    """Report a short, grep-able failure to the LH UI (Failures tab + logOutput)."""
    detail = " ".join(str(exc).split())[:800] or type(exc).__name__
    wf_run_id = _lh_id(getattr(ctx, "wf_run_id", None)) if ctx is not None else ""
    guid = _task_guid(ctx)
    parts = [f"{task_name} failed: {detail}"]
    if wf_run_id:
        parts.append(f"wf_run={wf_run_id}")
    if guid:
        parts.append(f"task_guid={guid}")
    parts.append("grep ECS worker logs for task_guid")
    message = "; ".join(parts)
    if ctx is not None:
        try:
            ctx.log(message)
        except Exception:
            pass
    logger.exception("%s", message)
    raise LHTaskException("STEP_FAILED", message) from exc


def _with_lh_failure(task_name: str, fn: Any) -> Any:
    """Convert uncaught exceptions into LHTaskException so the UI shows the message."""

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        ctx = kwargs.get("ctx")
        if ctx is None and args:
            last = args[-1]
            if isinstance(last, WorkerContext) or hasattr(last, "wf_run_id"):
                ctx = last
        try:
            return await fn(*args, **kwargs)
        except LHTaskException:
            raise
        except Exception as exc:
            _raise_step_failed(ctx, task_name, exc)

    return wrapped


def _company_names(companies: list[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in companies or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _require_service_urls() -> None:
    missing = []
    for task in HTTP_TASK_NAMES:
        env_key = f"SERVICE_URL_{task.upper().replace('-', '_')}"
        if not os.environ.get(env_key, "").strip():
            missing.append(env_key)
    if missing:
        raise RuntimeError(
            "Missing service URLs for workers. Set: " + ", ".join(sorted(missing))
        )


async def search_companies_task(
    icp_version: str,
    segment_ids: list[Any],
    max_leads: int,
    ctx: WorkerContext,
) -> list[Any]:
    limit = max_companies(default=int(max_leads))
    result = await post_json(
        "search-companies",
        "/v1/search-companies",
        {
            "icp_version": icp_version,
            "segment_ids": segment_ids,
            "max_results": limit,
        },
    )
    if not isinstance(result, list):
        raise TypeError(f"search-companies expected list, got {type(result)!r}")
    return result


async def score_companies_icp_task(
    icp_version: str,
    companies: list[Any],
    ctx: WorkerContext,
) -> list[Any]:
    result = await post_json(
        "score-companies-icp",
        "/v1/score-companies",
        {"icp_version": icp_version, "companies": companies},
    )
    if not isinstance(result, list):
        raise TypeError(f"score-companies-icp expected list, got {type(result)!r}")
    return result


async def select_top_leads_task(
    companies: list[Any],
    max_leads: int,
    ctx: WorkerContext,
) -> list[Any]:
    """Local: keep top N by icp_score (missing score sorts last)."""
    ranked = sorted(
        companies or [],
        key=lambda c: float((c or {}).get("icp_score") or 0.0),
        reverse=True,
    )
    limit = max_companies(default=max(0, int(max_leads)))
    selected = ranked[:limit]
    logger.info("select-top-leads kept %d of %d", len(selected), len(ranked))
    return selected


async def count_companies_task(
    companies: list[Any],
    ctx: WorkerContext,
) -> int:
    """Local: return number of companies from search-companies."""
    count = len(companies or [])
    logger.info("count-companies: %d", count)
    return count


async def find_decision_makers_task(
    company: dict[str, Any],
    icp_version: str,
    ctx: WorkerContext,
) -> dict[str, Any]:
    contacts = await post_json(
        "find-decision-makers",
        "/v1/find-decision-makers",
        {
            "company": company,
            "icp_version": icp_version,
            "max_results": max_contacts_per_company(),
        },
    )
    if not isinstance(contacts, list):
        raise TypeError(f"find-decision-makers expected list, got {type(contacts)!r}")
    return {
        "company": company,
        "contacts": contacts,
        "skill_matches": [],
        "hubspot_ids": {},
        "status": "enriched",
        "notes": None,
    }


async def sanitize_public_fields_task(
    lead: dict[str, Any], ctx: WorkerContext
) -> dict[str, Any]:
    result = await post_json(
        "sanitize-public-fields",
        "/v1/sanitize-public-fields",
        {"lead": lead},
    )
    if not isinstance(result, dict):
        raise TypeError(f"sanitize-public-fields expected dict, got {type(result)!r}")
    return result


async def extract_job_skills_task(lead: dict[str, Any], ctx: WorkerContext) -> dict[str, Any]:
    result = await post_json(
        "extract-job-skills",
        "/v1/extract-job-skills",
        lead,
    )
    if not isinstance(result, dict):
        raise TypeError(f"extract-job-skills expected dict, got {type(result)!r}")
    return result


async def fetch_ioet_skills_catalog_task(ctx: WorkerContext) -> str:
    """Local: pull BambooHR catalog once per parent campaign and persist to durable storage."""
    catalog_ref = _lh_id(ctx.wf_run_id)
    try:
        catalog = await asyncio.to_thread(fetch_skills_catalog)
    except Exception as exc:
        catalog = await asyncio.to_thread(load_skills_catalog, LATEST_CATALOG_REF)
        if catalog is None:
            raise
        logger.warning(
            "fetch-ioet-skills-catalog live fetch failed (%s); using last good snapshot "
            "(%d employees)",
            exc,
            len(catalog),
        )
    else:
        await asyncio.to_thread(save_skills_catalog, LATEST_CATALOG_REF, catalog)
    await asyncio.to_thread(save_skills_catalog, catalog_ref, catalog)
    logger.info(
        "fetch-ioet-skills-catalog ref=%s employees=%d",
        catalog_ref,
        len(catalog),
    )
    return catalog_ref


async def match_ioet_skills_task(
    lead: dict[str, Any],
    catalog_ref: str,
    ctx: WorkerContext,
) -> dict[str, Any]:
    catalog = await asyncio.to_thread(require_skills_catalog, catalog_ref)
    result = await post_json(
        "match-ioet-skills",
        "/v1/match-skills",
        {"lead": lead, "skills_catalog": catalog},
    )
    if not isinstance(result, dict):
        raise TypeError(f"match-ioet-skills expected dict, got {type(result)!r}")
    return result


async def draft_outreach_email_task(lead: dict[str, Any], ctx: WorkerContext) -> dict[str, Any]:
    result = await post_json(
        "draft-outreach-email",
        "/v1/draft-outreach-email",
        {"lead": lead},
    )
    if not isinstance(result, dict):
        raise TypeError(f"draft-outreach-email expected dict, got {type(result)!r}")
    return result


async def upsert_hubspot_task(
    lead: dict[str, Any], dry_run: bool, ctx: WorkerContext
) -> dict[str, Any]:
    result = await post_json(
        "upsert-hubspot",
        "/v1/upsert-lead",
        {"lead": lead, "dry_run": dry_run},
    )
    if not isinstance(result, dict):
        raise TypeError(f"upsert-hubspot expected dict, got {type(result)!r}")
    return result


async def build_campaign_summary_task(
    campaign_id: str,
    companies: list[Any],
    dry_run: bool,
    ctx: WorkerContext,
) -> dict[str, Any]:
    """Local: notification payload after fan-out completes."""
    count = len(companies or [])
    dry = " (dry-run)" if dry_run else ""
    names = _company_names(companies)
    message = (
        f"Leads campaign `{campaign_id}`{dry}: "
        f"{count} published, 0 failed, 0 skipped ({count} processed)."
    )
    if names:
        message += " Companies: " + ", ".join(names) + "."
    return {
        "message": message,
        "details": {
            "kind": "campaign_summary",
            "campaign_id": campaign_id,
            "leads_processed": count,
            "leads_published": count,
            "leads_failed": 0,
            "leads_skipped": 0,
            "company_names": names,
            "dry_run": bool(dry_run),
            "wf_run_id": _lh_id(ctx.wf_run_id),
        },
    }


async def build_empty_search_notification_task(
    icp_version: str,
    segment_ids: list[Any],
    campaign_id: str,
    ctx: WorkerContext,
) -> dict[str, Any]:
    """Local: notification payload when Apollo search returns no companies."""
    segments = ", ".join(str(s) for s in (segment_ids or [])) or "none"
    message = (
        f":mag: No companies found for campaign `{campaign_id}` "
        f"using ICP `{icp_version}` (segments: {segments})."
    )
    wf_run_id = _lh_id(ctx.wf_run_id)
    if wf_run_id:
        message += f" WfRun `{wf_run_id}`."
    return {
        "message": message,
        "details": {
            "kind": "empty_search",
            "campaign_id": campaign_id,
            "icp_version": icp_version,
            "segment_ids": segment_ids,
            "wf_run_id": wf_run_id,
        },
    }


async def notify_task(payload: dict[str, Any], ctx: WorkerContext) -> str:
    result = await post_json("notify", "/v1/notify", payload)
    if isinstance(result, dict):
        return str(result.get("status", "sent"))
    return "sent"


async def notify_failure_task(
    step_name: str,
    error_type: str,
    ctx: WorkerContext,
) -> str:
    wf_run_id = _lh_id(ctx.wf_run_id)
    result = await post_json(
        "notify-failure",
        "/v1/failure",
        {
            "campaign_id": wf_run_id,
            "wf_run_id": wf_run_id,
            "step_name": step_name,
            "error": error_type,
        },
    )
    if isinstance(result, dict):
        return str(result.get("status", "sent"))
    return "sent"


_RAW_TASK_HANDLERS: dict[str, Any] = {
    "search-companies": search_companies_task,
    "score-companies-icp": score_companies_icp_task,
    "select-top-leads": select_top_leads_task,
    "count-companies": count_companies_task,
    "find-decision-makers": find_decision_makers_task,
    "sanitize-public-fields": sanitize_public_fields_task,
    "extract-job-skills": extract_job_skills_task,
    "fetch-ioet-skills-catalog": fetch_ioet_skills_catalog_task,
    "match-ioet-skills": match_ioet_skills_task,
    "draft-outreach-email": draft_outreach_email_task,
    "upsert-hubspot": upsert_hubspot_task,
    "build-campaign-summary": build_campaign_summary_task,
    "build-empty-search-notification": build_empty_search_notification_task,
    "notify": notify_task,
    "notify-failure": notify_failure_task,
}

TASK_HANDLERS: dict[str, Any] = {
    name: _with_lh_failure(name, fn) for name, fn in _RAW_TASK_HANDLERS.items()
}


async def main() -> None:
    _require_service_urls()
    config = LHConfig()
    workers = [
        LHTaskWorker(TASK_HANDLERS[name], name, config) for name in TASK_NAMES
    ]
    logger.info("Starting %d task workers", len(workers))
    await littlehorse.start(*workers)


if __name__ == "__main__":
    asyncio.run(main())
