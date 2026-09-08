from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.common.sanitize import sanitize_lead
from services.common.schemas import LeadResult
from services.hubspot.client import HubSpotClient, HubSpotConfigError

router = APIRouter(prefix="/v1", tags=["hubspot"])


class UpsertLeadRequest(BaseModel):
    lead: LeadResult
    dry_run: bool = False


class SanitizeRequest(BaseModel):
    lead: LeadResult


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


@router.post("/upsert-lead")
def upsert_lead(request: UpsertLeadRequest) -> LeadResult:
    """Upsert company, contacts, and skill-match note in HubSpot."""
    try:
        return HubSpotClient().upsert_lead(request.lead, dry_run=request.dry_run)
    except HubSpotConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
