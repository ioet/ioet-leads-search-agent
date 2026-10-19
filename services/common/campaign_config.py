"""Campaign config models and Apollo/HubSpot override helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunMode(StrEnum):
    REVIEW = "review"
    LIVE = "live"
    DRY_RUN = "dry_run"


class HiringSignalMode(StrEnum):
    REQUIRED = "required"
    BOOST = "boost"
    IGNORE = "ignore"


class CompaniesFilterConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    employee_ranges: list[str] = Field(default_factory=list)
    hq_locations: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    recent_funding: str | None = None
    skip_customers: bool = True
    skip_open_deals: bool = True
    skip_has_owner: bool = True
    skip_contacted_within_days: int | None = 60


class HiringSignalConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: HiringSignalMode = HiringSignalMode.REQUIRED
    role_categories: list[str] = Field(default_factory=list)
    seniorities: list[str] = Field(default_factory=list)
    min_open_eng_roles: int | None = None
    posted_within_days: int | None = 30
    open_longer_than_days: int | None = None
    job_keywords: list[str] = Field(default_factory=list)
    job_locations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=lambda: ["apollo", "company_website"])


class DecisionMakersConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    personas: list[str] = Field(default_factory=list)
    email_requirement: str = "verified_only"
    phone_enrichment: str = "none"
    skip_when_no_email: bool = True
    contacts_per_company: int = 2


class HubspotOutputConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    if_company_exists: str = "add_job_note_only"
    if_contact_exists: str = "skip"
    lifecycle_stage: str = "lead"
    lead_status: str = "new"
    add_to_list: str | None = None
    follow_up_task_days: int | None = 2


class EmailDraftConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    offer: str = "staff_augmentation"
    angle: str = "hiring_signal"
    tone: str = "consultative"
    length: str = "short"
    call_to_action: str = "15_minute_call"
    language: str = "en"
    drafts_per_contact: int = 1
    save_as: str = "note"
    extra_instructions: str = Field(default="", max_length=500)


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_mode: RunMode = RunMode.DRY_RUN
    # Saved preference. Email delivery is not sent yet.
    email_owner: bool = True
    companies_per_run: int = Field(default=25, ge=1, le=500)
    # HubSpot company total shown as n/t. Reaching it does not stop scheduled runs.
    company_goal: int | None = Field(default=None, ge=1, le=1_000_000)
    # When set, the form flags an estimate above this many Apollo credits per run.
    credit_budget_per_run: int | None = Field(default=None, ge=1, le=1_000_000)
    companies_filter_config: CompaniesFilterConfig = Field(
        default_factory=CompaniesFilterConfig
    )
    hiring_signal_config: HiringSignalConfig = Field(default_factory=HiringSignalConfig)
    decision_makers_config: DecisionMakersConfig = Field(
        default_factory=DecisionMakersConfig
    )
    hubspot_output_config: HubspotOutputConfig = Field(default_factory=HubspotOutputConfig)
    email_draft_config: EmailDraftConfig = Field(default_factory=EmailDraftConfig)

    def model_dump_storage(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def parse_campaign_config(raw: dict[str, Any] | None) -> CampaignConfig:
    if not raw:
        return CampaignConfig()
    return CampaignConfig.model_validate(raw)


EMPLOYEE_BAND_TO_APOLLO: dict[str, list[str]] = {
    "1–10": ["1,10"],
    "1-10": ["1,10"],
    "11–50": ["11,20", "21,50"],
    "11-50": ["11,20", "21,50"],
    "51–200": ["51,100", "101,200"],
    "51-200": ["51,100", "101,200"],
    "201–500": ["201,500"],
    "201-500": ["201,500"],
    "501–1k": ["501,1000"],
    "501-1k": ["501,1000"],
    "1k+": ["1001,2000", "2001,5000", "5001,10000"],
}

HQ_LOCATION_TO_APOLLO: dict[str, str] = {
    "United States": "United States",
    "US": "United States",
    "Canada": "Canada",
    "CA": "Canada",
    "United Kingdom": "United Kingdom",
    "UK": "United Kingdom",
    "EU": "Europe",
}


def apollo_employee_ranges_from_filter(filt: CompaniesFilterConfig) -> list[str] | None:
    if not filt.employee_ranges:
        return None
    ranges: list[str] = []
    seen: set[str] = set()
    for band in filt.employee_ranges:
        for label in EMPLOYEE_BAND_TO_APOLLO.get(band, []):
            if label not in seen:
                seen.add(label)
                ranges.append(label)
    return ranges or None


def apollo_locations_from_filter(filt: CompaniesFilterConfig) -> list[str] | None:
    if not filt.hq_locations:
        return None
    return [HQ_LOCATION_TO_APOLLO.get(x, x) for x in filt.hq_locations] or None


def apply_company_filter_to_apollo_payload(
    payload: dict[str, Any],
    filt: CompaniesFilterConfig,
) -> dict[str, Any]:
    out = dict(payload)
    ranges = apollo_employee_ranges_from_filter(filt)
    if ranges is not None:
        out["organization_num_employees_ranges"] = ranges
    locs = apollo_locations_from_filter(filt)
    if locs is not None:
        out["organization_locations"] = locs
    if filt.tech_stack:
        tags = list(out.get("q_organization_keyword_tags") or [])
        for tech in filt.tech_stack:
            if tech and tech not in tags:
                tags.append(tech)
        out["q_organization_keyword_tags"] = tags
    return out


def persona_titles(dm: DecisionMakersConfig) -> list[str] | None:
    titles = [t.strip() for t in dm.personas if t and t.strip()]
    return titles or None
