"""LittleHorse task workers — thin HTTP bridge to microservices (+ local helpers)."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import sys
import threading
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
    "filter-hubspot-companies",
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

# Pure-local TaskDefs (no microservice SERVICE_URL_*); may still call the campaign API.
LOCAL_TASK_NAMES = [
    "select-top-leads",
    "build-campaign-summary",
    "build-empty-search-notification",
    "count-companies",
    "fetch-ioet-skills-catalog",
    "prepare-lead",
    "record-lead-outcome",
    "record-campaign-run",
    "fire-scheduled-campaign",
]

_lead_outcomes: dict[str, list[dict[str, Any]]] = {}
_lead_outcomes_lock = threading.Lock()

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
    icp_ref: str,
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> list[Any]:
    limit = max_companies(default=int(max_leads))
    payload: dict[str, Any] = {
        "icp_version": icp_version,
        "segment_ids": segment_ids,
        "max_results": limit,
        "campaign_config": campaign_config or {},
    }
    if icp_ref:
        payload["icp_ref"] = icp_ref
    result = await post_json("search-companies", "/v1/search-companies", payload)
    if not isinstance(result, list):
        raise TypeError(f"search-companies expected list, got {type(result)!r}")
    return result


async def filter_hubspot_companies_task(
    companies: list[Any],
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> list[Any]:
    result = await post_json(
        "filter-hubspot-companies",
        "/v1/filter-companies",
        {"companies": companies or [], "campaign_config": campaign_config or {}},
    )
    if not isinstance(result, list):
        raise TypeError(f"filter-hubspot-companies expected list, got {type(result)!r}")
    return result


async def score_companies_icp_task(
    icp_version: str,
    companies: list[Any],
    icp_ref: str,
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> list[Any]:
    payload: dict[str, Any] = {
        "icp_version": icp_version,
        "companies": companies,
        "campaign_config": campaign_config or {},
    }
    if icp_ref:
        payload["icp_ref"] = icp_ref
    result = await post_json("score-companies-icp", "/v1/score-companies", payload)
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


def _merge_notes(existing: Any, addition: str) -> str:
    text = str(existing).strip() if existing else ""
    if text:
        return f"{text}\n\n{addition.strip()}"
    return addition.strip()


def _skipped(lead: dict[str, Any]) -> bool:
    return str(lead.get("status") or "") == "skipped"


async def prepare_lead_task(company: dict[str, Any], ctx: WorkerContext) -> dict[str, Any]:
    """Turn a selected company into a lead before hiring-signal checks."""
    return {
        "company": company,
        "contacts": [],
        "skill_matches": [],
        "hubspot_ids": {},
        "status": "discovered",
        "notes": None,
    }


async def find_decision_makers_task(
    lead: dict[str, Any],
    icp_version: str,
    icp_ref: str,
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> dict[str, Any]:
    if _skipped(lead):
        return lead
    from services.common.campaign_config import parse_campaign_config

    company = lead.get("company") or {}
    cfg = parse_campaign_config(campaign_config or {})
    limit = cfg.decision_makers_config.contacts_per_company
    payload: dict[str, Any] = {
        "company": company,
        "icp_version": icp_version,
        "campaign_config": campaign_config or {},
        "max_results": limit if limit > 0 else max_contacts_per_company(),
    }
    if icp_ref:
        payload["icp_ref"] = icp_ref
    contacts = await post_json(
        "find-decision-makers",
        "/v1/find-decision-makers",
        payload,
    )
    if not isinstance(contacts, list):
        raise TypeError(f"find-decision-makers expected list, got {type(contacts)!r}")
    if not contacts and limit >= 1:
        note = "Skipped: no decision-maker contacts found."
        return {
            **lead,
            "contacts": [],
            "status": "skipped",
            "notes": _merge_notes(lead.get("notes"), note),
        }
    return {**lead, "contacts": contacts, "status": "enriched"}


async def sanitize_public_fields_task(
    lead: dict[str, Any], ctx: WorkerContext
) -> dict[str, Any]:
    if _skipped(lead):
        return lead
    result = await post_json(
        "sanitize-public-fields",
        "/v1/sanitize-public-fields",
        {"lead": lead},
    )
    if not isinstance(result, dict):
        raise TypeError(f"sanitize-public-fields expected dict, got {type(result)!r}")
    return result


async def extract_job_skills_task(
    lead: dict[str, Any],
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> dict[str, Any]:
    if _skipped(lead):
        return lead
    result = await post_json(
        "extract-job-skills",
        "/v1/extract-job-skills",
        {"lead": lead, "campaign_config": campaign_config or {}},
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
    if _skipped(lead):
        return lead
    catalog = await asyncio.to_thread(require_skills_catalog, catalog_ref)
    result = await post_json(
        "match-ioet-skills",
        "/v1/match-skills",
        {"lead": lead, "skills_catalog": catalog},
    )
    if not isinstance(result, dict):
        raise TypeError(f"match-ioet-skills expected dict, got {type(result)!r}")
    return result


async def draft_outreach_email_task(
    lead: dict[str, Any],
    campaign_config: dict[str, Any],
    ctx: WorkerContext,
) -> dict[str, Any]:
    if _skipped(lead) or not lead.get("contacts"):
        return lead
    result = await post_json(
        "draft-outreach-email",
        "/v1/draft-outreach-email",
        {"lead": lead, "campaign_config": campaign_config or {}},
    )
    if not isinstance(result, dict):
        raise TypeError(f"draft-outreach-email expected dict, got {type(result)!r}")
    return result


async def upsert_hubspot_task(
    lead: dict[str, Any],
    dry_run: bool,
    campaign_config: dict[str, Any],
    icp_ref: str,
    ctx: WorkerContext,
) -> dict[str, Any]:
    if _skipped(lead):
        return lead
    payload: dict[str, Any] = {
        "lead": lead,
        "dry_run": dry_run,
        "campaign_config": campaign_config or {},
    }
    if icp_ref:
        payload["icp_ref"] = icp_ref
    result = await post_json("upsert-hubspot", "/v1/upsert-lead", payload)
    if not isinstance(result, dict):
        raise TypeError(f"upsert-hubspot expected dict, got {type(result)!r}")
    return result


def _remember_outcome(run_id: str, outcome: dict[str, Any]) -> None:
    with _lead_outcomes_lock:
        _lead_outcomes.setdefault(run_id, []).append(outcome)


def _local_outcomes(run_id: str) -> list[dict[str, Any]]:
    with _lead_outcomes_lock:
        return list(_lead_outcomes.get(run_id, []))


def _outcome_status(lead: dict[str, Any], dry_run: bool) -> str:
    status = str(lead.get("status") or "")
    if status == "skipped":
        return "skipped"
    if status == "failed":
        return "failed"
    if dry_run:
        return "dry_run"
    return "published"


async def record_lead_outcome_task(
    run_id: str,
    lead: dict[str, Any],
    dry_run: bool,
    ctx: WorkerContext,
) -> dict[str, Any]:
    """Append one child result so the parent summary can count real outcomes."""
    company = lead.get("company") if isinstance(lead.get("company"), dict) else {}
    outcome = {
        "company_name": str((company or {}).get("name") or "unknown"),
        "status": _outcome_status(lead, dry_run),
        "contact_count": len(lead.get("contacts") or []),
        "note": (str(lead.get("notes")).strip()[:300] if lead.get("notes") else None),
    }
    run_id = (run_id or "").strip()
    if not run_id:
        return lead
    _remember_outcome(run_id, outcome)
    try:
        await _post_lead_outcome(run_id, outcome)
    except Exception as exc:
        logger.warning("record-lead-outcome kept in memory for %s: %s", run_id, exc)
    return lead


async def _post_lead_outcome(run_id: str, outcome: dict[str, Any]) -> None:
    from services.api import settings

    token = settings.internal_service_token()
    if not token:
        raise RuntimeError("API_INTERNAL_SERVICE_TOKEN unset")
    url = f"{settings.campaign_api_base_url()}/api/internal/runs/{run_id}/outcomes"

    def _post() -> None:
        import requests

        response = requests.post(
            url,
            json=outcome,
            headers={"X-Internal-Token": token},
            timeout=30,
        )
        if not response.ok:
            snippet = (response.text or response.reason or "").strip()[:400]
            raise RuntimeError(f"HTTP {response.status_code}: {snippet}")

    await asyncio.to_thread(_post)


async def _fetch_lead_outcomes(run_id: str) -> list[dict[str, Any]]:
    from services.api import settings

    token = settings.internal_service_token()
    if not token or not run_id.strip():
        return []
    url = f"{settings.campaign_api_base_url()}/api/internal/runs/{run_id.strip()}/outcomes"

    def _get() -> list[dict[str, Any]]:
        import requests

        response = requests.get(url, headers={"X-Internal-Token": token}, timeout=30)
        if not response.ok:
            return []
        body = response.json()
        items = body.get("outcomes") if isinstance(body, dict) else None
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    try:
        return await asyncio.to_thread(_get)
    except Exception as exc:
        logger.warning("Could not load lead outcomes for %s: %s", run_id, exc)
        return []


def _campaign_tag(campaign_id: str, campaign_name: str | None) -> str:
    name = (campaign_name or "").strip()
    return name or campaign_id


async def _lookup_campaign_name(campaign_id: str) -> str:
    """Campaign name for Slack. Empty when the API is unavailable."""
    from services.api import settings

    campaign_id = (campaign_id or "").strip()
    token = settings.internal_service_token()
    if not token or not campaign_id or campaign_id == "unsaved-test":
        return ""
    url = f"{settings.campaign_api_base_url()}/api/internal/campaigns/{campaign_id}"

    def _get() -> str:
        import requests

        response = requests.get(url, headers={"X-Internal-Token": token}, timeout=30)
        if not response.ok:
            return ""
        body = response.json()
        if not isinstance(body, dict):
            return ""
        return str(body.get("name") or "").strip()

    try:
        return await asyncio.to_thread(_get)
    except Exception as exc:
        logger.warning("Could not load campaign name for %s: %s", campaign_id, exc)
        return ""


async def build_campaign_summary_task(
    campaign_id: str,
    companies: list[Any],
    dry_run: bool,
    run_id: str,
    ctx: WorkerContext,
) -> dict[str, Any]:
    """Local: notification payload after fan-out completes."""
    count = len(companies or [])
    dry = " (dry-run)" if dry_run else ""
    label = _campaign_tag(campaign_id, await _lookup_campaign_name(campaign_id))
    outcomes = await _fetch_lead_outcomes(run_id or "")
    if not outcomes and (run_id or "").strip():
        outcomes = _local_outcomes(run_id.strip())
    names = [str(item.get("company_name")) for item in outcomes if item.get("company_name")]
    if not names:
        names = _company_names(companies)
    if outcomes:
        published = sum(1 for item in outcomes if item.get("status") == "published")
        dry_count = sum(1 for item in outcomes if item.get("status") == "dry_run")
        failed = sum(1 for item in outcomes if item.get("status") == "failed")
        skipped = sum(1 for item in outcomes if item.get("status") == "skipped")
        message = (
            f"Leads campaign `{label}`{dry}: "
            f"{published} published, {dry_count} dry-run, {failed} failed, "
            f"{skipped} skipped ({count} selected)."
        )
        leads_published = published
        leads_failed = failed
        leads_skipped = skipped
    else:
        published = dry_count = failed = skipped = 0
        message = (
            f"Leads campaign `{label}`{dry}: "
            f"{count} companies selected; child outcomes were not recorded."
        )
        leads_published = 0
        leads_failed = 0
        leads_skipped = 0
    if names:
        message += " Companies: " + ", ".join(names) + "."
    return {
        "message": message,
        "details": {
            "kind": "campaign_summary",
            "campaign_id": campaign_id,
            "leads_processed": count,
            "leads_published": leads_published,
            "leads_dry_run": dry_count,
            "leads_failed": leads_failed,
            "leads_skipped": leads_skipped,
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
    label = _campaign_tag(campaign_id, await _lookup_campaign_name(campaign_id))
    message = (
        f":mag: No companies found for campaign `{label}` "
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
    try:
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
    except Exception as exc:
        # Slack/notify being down must not block recording the campaign run.
        logger.warning("notify-failure skipped (%s): %s", step_name, exc)
        return "skipped"
    if isinstance(result, dict):
        return str(result.get("status", "sent"))
    return "sent"


async def fire_scheduled_campaign_task(schedule_id: str, ctx: WorkerContext) -> str:
    """Ask the campaign API to start a run for this schedule id."""
    from services.api import settings

    schedule_id = (schedule_id or "").strip()
    if not schedule_id:
        raise RuntimeError("fire-scheduled-campaign missing schedule-id")

    base = settings.campaign_api_base_url()
    token = settings.internal_service_token()
    if not token:
        raise RuntimeError("API_INTERNAL_SERVICE_TOKEN unset")

    url = f"{base}/api/internal/schedules/{schedule_id}/fire"

    def _post() -> Any:
        import requests

        response = requests.post(
            url,
            headers={"X-Internal-Token": token},
            timeout=120,
        )
        if not response.ok:
            snippet = (response.text or response.reason or "").strip()[:400]
            raise RuntimeError(
                f"fire-scheduled-campaign HTTP {response.status_code}: {snippet}"
            )
        return response.json()

    result = await asyncio.to_thread(_post)
    run_id = result.get("run_id") if isinstance(result, dict) else None
    logger.info("fire-scheduled-campaign schedule=%s run=%s", schedule_id, run_id)
    return str(run_id or "fired")


async def record_campaign_run_task(
    run_id: str,
    summary: dict[str, Any],
    status: str,
    ctx: WorkerContext,
) -> str:
    """POST run completion to the campaign API. No-op when run_id is empty (lhctl)."""
    run_id = (run_id or "").strip()
    if not run_id:
        logger.info("record-campaign-run skipped (empty run-id)")
        return "skipped"

    from services.api import settings

    base = settings.campaign_api_base_url()
    token = settings.internal_service_token()
    if not token:
        logger.warning("API_INTERNAL_SERVICE_TOKEN unset; cannot record run %s", run_id)
        return "skipped-no-token"

    url = f"{base}/api/internal/runs/{run_id}/complete"
    payload = {
        "status": status if status in {"completed", "failed"} else "completed",
        "result_summary": summary if isinstance(summary, dict) else {"raw": summary},
        "lh_wf_run_id": _lh_id(ctx.wf_run_id) or None,
    }

    def _post() -> Any:
        import requests

        response = requests.post(
            url,
            json=payload,
            headers={"X-Internal-Token": token},
            timeout=60,
        )
        if not response.ok:
            snippet = (response.text or response.reason or "").strip()[:400]
            raise RuntimeError(
                f"record-campaign-run HTTP {response.status_code}: {snippet}"
            )
        return response.json()

    await asyncio.to_thread(_post)
    logger.info("record-campaign-run updated %s → %s", run_id, payload["status"])
    return "recorded"


_RAW_TASK_HANDLERS: dict[str, Any] = {
    "search-companies": search_companies_task,
    "filter-hubspot-companies": filter_hubspot_companies_task,
    "score-companies-icp": score_companies_icp_task,
    "select-top-leads": select_top_leads_task,
    "count-companies": count_companies_task,
    "prepare-lead": prepare_lead_task,
    "find-decision-makers": find_decision_makers_task,
    "sanitize-public-fields": sanitize_public_fields_task,
    "extract-job-skills": extract_job_skills_task,
    "fetch-ioet-skills-catalog": fetch_ioet_skills_catalog_task,
    "match-ioet-skills": match_ioet_skills_task,
    "draft-outreach-email": draft_outreach_email_task,
    "upsert-hubspot": upsert_hubspot_task,
    "build-campaign-summary": build_campaign_summary_task,
    "build-empty-search-notification": build_empty_search_notification_task,
    "record-lead-outcome": record_lead_outcome_task,
    "record-campaign-run": record_campaign_run_task,
    "fire-scheduled-campaign": fire_scheduled_campaign_task,
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
