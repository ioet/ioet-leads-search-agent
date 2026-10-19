"""Entity request/response models (DB metadata only; ICP JSON lives in object storage)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.api.schemas.campaign_config import CampaignConfig


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"


class ScheduleType(StrEnum):
    ONCE = "once"
    RECURRING = "recurring"


class RunTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IcpCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    icp: dict[str, Any]
    upload_id: str | None = None
    source_filename: str | None = None


class IcpPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    icp_id: str
    title: str
    pdf_s3_uri: str | None = None
    icp_json_s3_uri: str
    version: str | None = None
    created_by: str
    created_at: str
    updated_at: str


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    icp_id: str
    owner_user_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: CampaignStatus = CampaignStatus.DRAFT
    config: CampaignConfig = Field(default_factory=CampaignConfig)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    icp_id: str | None = None
    owner_user_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: CampaignStatus | None = None
    config: CampaignConfig | None = None


class CampaignPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: str
    name: str
    owner_user_id: str
    owner_name: str | None = None
    icp_id: str
    start_date: str | None = None
    end_date: str | None = None
    status: CampaignStatus
    config: CampaignConfig
    companies_upserted: int = 0
    created_at: str
    updated_at: str


class UserDirectoryEntry(BaseModel):
    user_id: str
    email: str
    name: str


class ScheduleCreate(BaseModel):
    type: ScheduleType
    # ISO datetime for once; unix cron (5 fields) for recurring
    expression: str = Field(min_length=1, max_length=120)
    timezone: str = "UTC"
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    expression: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    enabled: bool | None = None


class SchedulePublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schedule_id: str
    campaign_id: str
    type: ScheduleType
    expression: str
    timezone: str
    enabled: bool
    lh_schedule_id: str | None = None
    created_at: str
    updated_at: str


class TestRunCreate(BaseModel):
    """Start a dry-run workflow from unsaved campaign fields."""

    name: str = ""
    icp_id: str
    config: CampaignConfig = Field(default_factory=CampaignConfig)


class TestRunPublic(BaseModel):
    lh_wf_run_id: str
    dry_run: bool = True
    companies_per_run: int


class CampaignRunCreate(BaseModel):
    """Create a run record without starting LittleHorse (Phase 2). Phase 3 wires trigger."""

    trigger: RunTrigger = RunTrigger.MANUAL


class CampaignRunPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    campaign_id: str
    campaign_name: str
    trigger: RunTrigger
    status: RunStatus
    started_at: str | None = None
    ended_at: str | None = None
    lh_wf_run_id: str | None = None
    result_summary: dict[str, Any] | None = None
    created_at: str
    updated_at: str
