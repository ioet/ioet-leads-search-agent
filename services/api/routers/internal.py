"""Internal endpoints called by LittleHorse workers (service-token auth)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from services.api import settings
from services.api.run_starter import RunStartError, start_campaign_run
from services.api.schedule_sync import unsync_schedule_from_lh
from services.api.schemas.entities import (
    CampaignRunPublic,
    CampaignStatus,
    RunStatus,
    RunTrigger,
    ScheduleType,
)
from services.api.stores import campaign_runs as run_store
from services.api.stores import campaigns as campaign_store
from services.api.stores import schedules as schedule_store
from services.api.stores.campaign_runs import CampaignRunNotFoundError
from services.api.stores.campaigns import CampaignNotFoundError
from services.api.stores.schedules import ScheduleNotFoundError

router = APIRouter(prefix="/internal", tags=["internal"])


class CompleteRunRequest(BaseModel):
    status: RunStatus = RunStatus.COMPLETED
    result_summary: dict[str, Any] | None = None
    lh_wf_run_id: str | None = None


class LeadOutcomeRequest(BaseModel):
    company_name: str
    status: str
    contact_count: int = 0
    note: str | None = None


def _published_companies(summary: dict[str, Any] | None) -> int:
    """Companies this run wrote to HubSpot. Dry-run outcomes are not included."""
    if not isinstance(summary, dict):
        return 0
    details = summary.get("details")
    if not isinstance(details, dict):
        return 0
    raw = details.get("leads_published")
    try:
        return max(int(raw or 0), 0)
    except (TypeError, ValueError):
        return 0


def _require_internal_token(x_internal_token: str | None) -> None:
    expected = settings.internal_service_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_INTERNAL_SERVICE_TOKEN is not configured",
        )
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )


@router.get("/campaigns/{campaign_id}")
def get_campaign_name(
    campaign_id: str,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, str]:
    """Name used to tag Slack summaries. Workers already know the campaign id."""
    _require_internal_token(x_internal_token)
    try:
        campaign = campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    return {"campaign_id": campaign.campaign_id, "name": campaign.name}


@router.post("/runs/{run_id}/complete", response_model=CampaignRunPublic)
def complete_run(
    run_id: str,
    body: CompleteRunRequest,
    x_internal_token: str | None = Header(default=None),
) -> CampaignRunPublic:
    _require_internal_token(x_internal_token)
    if body.status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be completed or failed",
        )
    try:
        run = run_store.complete_run(
            run_id,
            status=body.status,
            result_summary=body.result_summary,
            lh_wf_run_id=body.lh_wf_run_id,
        )
    except CampaignRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    published = _published_companies(body.result_summary)
    try:
        added = run_store.credit_published_companies(run_id, published)
        if added:
            campaign_store.add_companies_upserted(run.campaign_id, added)
    except (CampaignRunNotFoundError, CampaignNotFoundError):
        pass
    return run


@router.post("/runs/{run_id}/outcomes", status_code=status.HTTP_204_NO_CONTENT)
def add_lead_outcome(
    run_id: str,
    body: LeadOutcomeRequest,
    x_internal_token: str | None = Header(default=None),
) -> None:
    _require_internal_token(x_internal_token)
    try:
        run_store.append_lead_outcome(run_id, body.model_dump())
    except CampaignRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@router.get("/runs/{run_id}/outcomes")
def get_lead_outcomes(
    run_id: str,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_internal_token(x_internal_token)
    try:
        run_store.require_run(run_id)
    except CampaignRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return {"outcomes": run_store.list_lead_outcomes(run_id)}


@router.post("/schedules/{schedule_id}/fire", response_model=CampaignRunPublic)
def fire_schedule(
    schedule_id: str,
    x_internal_token: str | None = Header(default=None),
) -> CampaignRunPublic:
    """Called by the fire-scheduled-campaign worker when a LH cron ticks."""
    _require_internal_token(x_internal_token)
    try:
        schedule = schedule_store.require_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc

    if not schedule.enabled:
        raise HTTPException(status_code=400, detail="Schedule is disabled")

    try:
        campaign = campaign_store.require_campaign(schedule.campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc

    if campaign.status == CampaignStatus.ENDED:
        unsync_schedule_from_lh(schedule)
        raise HTTPException(status_code=400, detail="Campaign has ended")

    try:
        run = start_campaign_run(campaign=campaign, trigger=RunTrigger.SCHEDULED)
    except RunStartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # One-shot schedules: tear down LH after the first fire.
    if schedule.type == ScheduleType.ONCE:
        unsync_schedule_from_lh(schedule)
        schedule_store.update_schedule(schedule.schedule_id, enabled=False)

    return run
