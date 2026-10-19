"""Campaign, schedule, and run CRUD."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from services.api.auth.deps import current_user
from services.api.models import UserRecord
from services.api.run_starter import RunStartError, start_campaign_run, start_unsaved_dry_run
from services.api.schedule_sync import (
    ScheduleSyncError,
    sync_schedule_to_lh,
    unsync_all_for_campaign,
    unsync_schedule_from_lh,
)
from services.api.schemas.entities import (
    CampaignCreate,
    CampaignPublic,
    CampaignRunCreate,
    CampaignRunPublic,
    CampaignStatus,
    CampaignUpdate,
    TestRunCreate,
    TestRunPublic,
    UserDirectoryEntry,
    ScheduleCreate,
    SchedulePublic,
    ScheduleUpdate,
)
from services.api.stores import campaign_runs as run_store
from services.api.stores import campaigns as campaign_store
from services.api.stores import icps as icp_store
from services.api.stores import schedules as schedule_store
from services.api.stores import users as user_store
from services.api.stores.users import display_name
from services.api.stores.campaign_runs import CampaignRunNotFoundError
from services.api.stores.campaigns import CampaignNotFoundError
from services.api.stores.icps import IcpNotFoundError
from services.api.stores.schedules import ScheduleNotFoundError

router = APIRouter(tags=["campaigns"])


def _owner_from_id(user_id: str) -> tuple[str, str]:
    try:
        owner = user_store.get_user(user_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unknown owner") from exc
    if owner is None:
        raise HTTPException(status_code=400, detail="Unknown owner")
    return owner.user_id, display_name(owner)


@router.get("/campaigns", response_model=list[CampaignPublic])
def list_campaigns(
    _: Annotated[UserRecord, Depends(current_user)],
) -> list[CampaignPublic]:
    return campaign_store.list_campaigns()


@router.post("/campaigns", response_model=CampaignPublic, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignCreate,
    user: Annotated[UserRecord, Depends(current_user)],
) -> CampaignPublic:
    try:
        icp_store.require_icp(body.icp_id)
    except IcpNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Unknown icp_id") from exc
    owner_user_id, owner_name = _owner_from_id(body.owner_user_id or user.user_id)
    return campaign_store.create_campaign(
        name=body.name,
        owner_user_id=owner_user_id,
        owner_name=owner_name,
        icp_id=body.icp_id,
        start_date=body.start_date,
        end_date=body.end_date,
        status=body.status,
        config=body.config,
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignPublic)
def get_campaign(
    campaign_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> CampaignPublic:
    try:
        return campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc


@router.patch("/campaigns/{campaign_id}", response_model=CampaignPublic)
def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    _: Annotated[UserRecord, Depends(current_user)],
) -> CampaignPublic:
    if body.icp_id is not None:
        try:
            icp_store.require_icp(body.icp_id)
        except IcpNotFoundError as exc:
            raise HTTPException(status_code=400, detail="Unknown icp_id") from exc
    owner_user_id = None
    owner_name = None
    if body.owner_user_id is not None:
        owner_user_id, owner_name = _owner_from_id(body.owner_user_id)
    try:
        updated = campaign_store.update_campaign(
            campaign_id,
            name=body.name,
            owner_user_id=owner_user_id,
            owner_name=owner_name,
            icp_id=body.icp_id,
            start_date=body.start_date,
            end_date=body.end_date,
            status=body.status,
            config=body.config,
        )
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    if body.status == CampaignStatus.ENDED:
        unsync_all_for_campaign(campaign_id)
    return updated


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> None:
    try:
        for schedule in schedule_store.list_schedules_for_campaign(campaign_id):
            unsync_schedule_from_lh(schedule)
            schedule_store.delete_schedule(schedule.schedule_id)
        campaign_store.delete_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc


# --- Schedules ---


@router.get("/campaigns/{campaign_id}/schedules", response_model=list[SchedulePublic])
def list_schedules(
    campaign_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> list[SchedulePublic]:
    try:
        campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    return schedule_store.list_schedules_for_campaign(campaign_id)


@router.post(
    "/campaigns/{campaign_id}/schedules",
    response_model=SchedulePublic,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    campaign_id: str,
    body: ScheduleCreate,
    _: Annotated[UserRecord, Depends(current_user)],
) -> SchedulePublic:
    try:
        campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    created = schedule_store.create_schedule(
        campaign_id=campaign_id,
        type=body.type,
        expression=body.expression,
        timezone=body.timezone,
        enabled=body.enabled,
    )
    try:
        return sync_schedule_to_lh(created)
    except ScheduleSyncError as exc:
        schedule_store.delete_schedule(created.schedule_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.patch("/schedules/{schedule_id}", response_model=SchedulePublic)
def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    _: Annotated[UserRecord, Depends(current_user)],
) -> SchedulePublic:
    try:
        updated = schedule_store.update_schedule(
            schedule_id,
            expression=body.expression,
            timezone=body.timezone,
            enabled=body.enabled,
        )
        return sync_schedule_to_lh(updated)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ScheduleSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> None:
    try:
        schedule = schedule_store.require_schedule(schedule_id)
        unsync_schedule_from_lh(schedule)
        schedule_store.delete_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc


@router.post("/campaigns/test-run", response_model=TestRunPublic)
def test_run(
    body: TestRunCreate,
    _: Annotated[UserRecord, Depends(current_user)],
) -> TestRunPublic:
    """Dry-run the current form. Does not write a campaign, a run row, or HubSpot."""
    try:
        lh_id = start_unsaved_dry_run(name=body.name, icp_id=body.icp_id, config=body.config)
    except RunStartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestRunPublic(
        lh_wf_run_id=lh_id,
        companies_per_run=body.config.companies_per_run,
    )


# --- Runs (creates a CampaignRun and starts LittleHorse) ---


@router.get("/campaigns/{campaign_id}/runs", response_model=list[CampaignRunPublic])
def list_runs(
    campaign_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> list[CampaignRunPublic]:
    try:
        campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    return run_store.list_runs_for_campaign(campaign_id)


@router.post(
    "/campaigns/{campaign_id}/runs",
    response_model=CampaignRunPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_run(
    campaign_id: str,
    body: CampaignRunCreate,
    _: Annotated[UserRecord, Depends(current_user)],
) -> CampaignRunPublic:
    try:
        campaign = campaign_store.require_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc
    try:
        return start_campaign_run(campaign=campaign, trigger=body.trigger)
    except RunStartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=CampaignRunPublic)
def get_run(
    run_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> CampaignRunPublic:
    try:
        return run_store.require_run(run_id)
    except CampaignRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
