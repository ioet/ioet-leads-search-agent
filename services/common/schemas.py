"""Shared request/response models for workflow tasks and HTTP services."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from services.common.limits import max_companies, max_contacts_per_company


class LeadStatus(str, Enum):
    DISCOVERED = "discovered"
    SCORED = "scored"
    ENRICHED = "enriched"
    MATCHED = "matched"
    PUBLISHED = "published"
    SKIPPED = "skipped"
    FAILED = "failed"


class WorkflowRunInput(BaseModel):
    icp_version: str
    segment_ids: list[str] = Field(default_factory=lambda: ["primary"])
    campaign_id: str
    max_leads: int = Field(default_factory=lambda: max_companies(25), ge=1, le=500)
    dry_run: bool = False


class CompanySearchRequest(BaseModel):
    icp_version: str | None = None
    icp_ref: str | None = None
    segment_ids: list[str]
    max_results: int = Field(default_factory=lambda: max_companies(25), ge=1, le=500)
    campaign_config: dict[str, Any] | None = None


class Company(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None
    linkedin_url: str | None = None
    employee_count: int | None = None
    segment_id: str | None = None
    icp_score: float | None = None
    rationale: str | None = None
    signals: list[str] = Field(default_factory=list)
    notes: str | None = None
    apollo_organization_id: str | None = None


class Contact(BaseModel):
    full_name: str
    title: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    persona_tier: int | None = None
    notes: str | None = None


class SkillMatch(BaseModel):
    skill: str
    person_or_team: str
    confidence: float = Field(ge=0.0, le=1.0)


class JobPosting(BaseModel):
    """Public job posting discovered from an external source."""

    title: str
    source: str  # e.g. linkedin, company_website — extensible registry id
    description: str
    url: str | None = None
    location: str | None = None


class JobPostingContext(BaseModel):
    """Aggregated job-posting search + skill extraction for a lead."""

    postings: list[JobPosting] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    sources_searched: list[str] = Field(default_factory=list)
    note: str | None = None


class LeadResult(BaseModel):
    company: Company
    contacts: list[Contact] = Field(default_factory=list)
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    job_context: JobPostingContext | None = None
    hubspot_ids: dict[str, str] = Field(default_factory=dict)
    status: LeadStatus = LeadStatus.DISCOVERED
    notes: str | None = None


class CampaignSummary(BaseModel):
    campaign_id: str
    leads_processed: int = 0
    leads_published: int = 0
    leads_failed: int = 0
    leads_skipped: int = 0
    dry_run: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class NotifyRequest(BaseModel):
    """Slack notification payload — service posts message as-is to the webhook."""

    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
