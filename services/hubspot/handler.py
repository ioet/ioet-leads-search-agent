from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.common.campaign_config import parse_campaign_config
from services.common.sanitize import sanitize_lead
from services.common.schemas import Company, LeadResult
from services.hubspot.client import HubSpotClient, HubSpotConfigError
from services.hubspot.filter import filter_companies

router = APIRouter(prefix="/v1", tags=["hubspot"])


class UpsertLeadRequest(BaseModel):
    lead: LeadResult
    dry_run: bool = False
    campaign_config: dict[str, Any] | None = None
    icp_ref: str | None = None


class SanitizeRequest(BaseModel):
    lead: LeadResult


class FilterCompaniesRequest(BaseModel):
    companies: list[Company] = Field(default_factory=list)
    campaign_config: dict[str, Any] | None = None


@router.post("/sanitize-public-fields")
def sanitize_public_fields(request: SanitizeRequest) -> LeadResult:
    """Strip sensitive fields before CRM publish / further enrichment."""
    return sanitize_lead(request.lead)


@router.get("/verify")
def verify() -> dict:
    """Confirm HUBSPOT_SERVICE_KEY works with a read-only HubSpot call (no writes)."""
    try:
        return HubSpotClient().verify()
    except HubSpotConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface API auth/scope errors to caller
        raise HTTPException(status_code=502, detail=f"HubSpot verify failed: {exc}") from exc


@router.post("/filter-companies")
def filter_companies_endpoint(request: FilterCompaniesRequest) -> list[Company]:
    """Drop companies that match campaign HubSpot skip rules (best-effort scopes)."""
    cfg = parse_campaign_config(request.campaign_config)
    filt = cfg.companies_filter_config
    if not request.companies:
        return []
    try:
        client = HubSpotClient()
    except HubSpotConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    signals_by_domain: dict[str, dict[str, Any]] = {}
    for company in request.companies:
        key = (company.domain or "").lower()
        if not key or key in signals_by_domain:
            continue
        signals_by_domain[key] = client.company_signals(company)

    return filter_companies(request.companies, signals_by_domain, filt)


@router.post("/upsert-lead")
def upsert_lead(request: UpsertLeadRequest) -> LeadResult:
    """Upsert company, contacts, and skill-match note in HubSpot."""
    try:
        cfg = parse_campaign_config(request.campaign_config)
        return HubSpotClient().upsert_lead(
            request.lead,
            dry_run=request.dry_run,
            output_config=cfg.hubspot_output_config,
            icp_ref=request.icp_ref,
        )
    except HubSpotConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
