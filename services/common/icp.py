"""Ideal Customer Profile models and loaders.

Canonical data lives in ``data/icp.json`` (transcribed from ioet_Current_ICP.pdf).
"""

from __future__ import annotations

import json
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Repo root: services/common/icp.py -> parents[2]
DEFAULT_ICP_PATH = Path(__file__).resolve().parents[2] / "data" / "icp.json"


class MessagingAngle(str, Enum):
    EXEC_ROI = "exec_roi"
    TEAM_CAPACITY = "team_capacity"


class EmployeeCountRange(BaseModel):
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @field_validator("max")
    @classmethod
    def max_gte_min(cls, v: int, info: Any) -> int:
        minimum = info.data.get("min")
        if minimum is not None and v < minimum:
            raise ValueError("employee_count.max must be >= min")
        return v


class CompanySizeHint(BaseModel):
    min_employees: int | None = Field(default=None, ge=1)
    max_employees: int | None = Field(default=None, ge=1)


class SegmentSourcing(BaseModel):
    yc_batches: list[str] = Field(default_factory=list)
    yc_preferred: bool = False


class Segment(BaseModel):
    id: str
    definition: str
    in_outbound: bool
    priority: int | None = None
    volume: str | None = None
    industries: list[str] = Field(default_factory=list)
    employee_count: EmployeeCountRange | None = None
    funding_stages: list[str] = Field(default_factory=list)
    geos: list[str] = Field(default_factory=list)
    sourcing: SegmentSourcing | None = None
    examples: list[str] = Field(default_factory=list)
    reason: str | None = None


class BuyerPersona(BaseModel):
    tier: int = Field(ge=1, le=3)
    titles: list[str] = Field(min_length=1)
    company_size_hint: CompanySizeHint = Field(default_factory=CompanySizeHint)
    messaging: MessagingAngle
    reach_with: list[int] = Field(default_factory=list)
    secondary_contact: bool = False


class Systems(BaseModel):
    company_search: str
    contact_enrichment: str
    crm: str
    skills: str | None = None
    llm: str | None = None


class DataPolicy(BaseModel):
    hubspot_allowlist: list[str]
    hubspot_denylist: list[str]


class IdealCustomerProfile(BaseModel):
    version: str
    source: str
    prepared_by: str
    campaign: str
    segments: list[Segment] = Field(min_length=1)
    buyer_personas: list[BuyerPersona] = Field(min_length=1)
    prioritization_signals: list[str] = Field(default_factory=list)
    systems: Systems
    data_policy: DataPolicy

    def segment_by_id(self, segment_id: str) -> Segment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise KeyError(f"Unknown segment id: {segment_id!r}")

    def segments_by_ids(self, segment_ids: list[str]) -> list[Segment]:
        return [self.segment_by_id(sid) for sid in segment_ids]


def load_icp(path: Path | str | None = None) -> IdealCustomerProfile:
    """Load and validate the canonical ICP JSON (local file or S3)."""
    if path is not None:
        icp_path = Path(path)
        raw = json.loads(icp_path.read_text(encoding="utf-8"))
        return IdealCustomerProfile.model_validate(raw)

    bucket = os.environ.get("ICP_S3_BUCKET", "").strip()
    key = os.environ.get("ICP_S3_KEY", "").strip()
    if bucket and key:
        return _load_icp_from_s3(bucket, key)

    raw = json.loads(DEFAULT_ICP_PATH.read_text(encoding="utf-8"))
    return IdealCustomerProfile.model_validate(raw)


@lru_cache(maxsize=4)
def _load_icp_from_s3(bucket: str, key: str) -> IdealCustomerProfile:
    import boto3

    client = boto3.client("s3")
    obj = client.get_object(Bucket=bucket, Key=key)
    raw = json.loads(obj["Body"].read().decode("utf-8"))
    return IdealCustomerProfile.model_validate(raw)


def outbound_segments(
    icp: IdealCustomerProfile,
    segment_ids: list[str] | None = None,
) -> list[Segment]:
    """Return outbound-eligible segments, optionally filtered by id."""
    selected = (
        icp.segments_by_ids(segment_ids) if segment_ids is not None else icp.segments
    )
    return [s for s in selected if s.in_outbound]


def titles_for_company_size(
    icp: IdealCustomerProfile,
    employee_count: int | None,
) -> list[str]:
    """Pick buyer titles from persona tiers based on company size hints.

    Tier 1 is always included (founder/exec first contact, including at larger cos).
    Tier 2+ apply when ``employee_count`` meets their ``min_employees`` hint.
    Unknown size defaults to Tier 1 only.
    """
    personas = sorted(icp.buyer_personas, key=lambda p: p.tier)
    titles: list[str] = []

    for persona in personas:
        if persona.tier == 1:
            titles.extend(persona.titles)
            continue
        if employee_count is None:
            continue
        hint = persona.company_size_hint
        if hint.min_employees is not None and employee_count >= hint.min_employees:
            titles.extend(persona.titles)

    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        if title not in seen:
            seen.add(title)
            unique.append(title)
    return unique


def apollo_hard_filters(segment: Segment) -> dict[str, Any]:
    """Map a segment to Apollo-oriented hard filter fields."""
    if not segment.in_outbound:
        raise ValueError(f"Segment {segment.id!r} is not in outbound scope")
    return {
        "segment_id": segment.id,
        "industries": list(segment.industries),
        "employee_count_min": segment.employee_count.min if segment.employee_count else None,
        "employee_count_max": segment.employee_count.max if segment.employee_count else None,
        "funding_stages": list(segment.funding_stages),
        "geos": list(segment.geos),
        "yc_preferred": bool(segment.sourcing.yc_preferred) if segment.sourcing else False,
        "yc_batches": list(segment.sourcing.yc_batches) if segment.sourcing else [],
    }
