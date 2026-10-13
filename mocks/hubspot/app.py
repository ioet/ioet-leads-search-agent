"""Mock HubSpot microservice — same HTTP contract as services/hubspot."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from mocks.common.logging import RequestResponseLogMiddleware, configure_logging
from mocks.hubspot.persistence import output_dir, persist_store, persist_upsert
from services.common.sanitize import hubspot_payload_from_lead, sanitize_lead
from services.common.schemas import LeadResult, LeadStatus

configure_logging()
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["hubspot-mock"])

# In-memory store for demo inspection.
CRM_STORE: dict[str, Any] = {"companies": {}, "contacts": {}, "notes": []}


class UpsertLeadRequest(BaseModel):
    lead: LeadResult
    dry_run: bool = False


class SanitizeRequest(BaseModel):
    lead: LeadResult


@router.get("/store")
def read_store() -> dict[str, Any]:
    """Inspect what the mock CRM received (demo helper)."""
    return {
        **CRM_STORE,
        "_output_dir": str(output_dir()),
    }


@router.post("/sanitize-public-fields")
def sanitize_public_fields(request: SanitizeRequest) -> LeadResult:
    return sanitize_lead(request.lead)


@router.post("/upsert-lead")
def upsert_lead(request: UpsertLeadRequest) -> LeadResult:
    clean = sanitize_lead(request.lead)
    payload = hubspot_payload_from_lead(clean)
    prefix = "dry-run" if request.dry_run else "mock"

    company_key = clean.company.domain or clean.company.name
    company_id = f"{prefix}-company-{uuid.uuid4().hex[:8]}"
    company_props = payload.get("company") or {}
    company_ref = {
        "id": company_id,
        "key": company_key,
        "name": company_props.get("name"),
        "domain": company_props.get("domain"),
    }
    CRM_STORE["companies"][company_key] = {
        "id": company_id,
        "properties": company_props,
        "dry_run": request.dry_run,
    }

    ids: dict[str, str] = {"company": company_id}
    for idx, contact in enumerate(payload.get("contacts") or []):
        contact_id = f"{prefix}-contact-{uuid.uuid4().hex[:8]}"
        ids[f"contact_{idx}"] = contact_id
        CRM_STORE["contacts"][contact_id] = {
            **contact,
            "company": company_ref,
        }

    company_note = payload.get("company_note")
    if company_note:
        note_id = f"{prefix}-note-{uuid.uuid4().hex[:8]}"
        ids["note"] = note_id
        CRM_STORE["notes"].append(
            {
                "id": note_id,
                "company_id": company_id,
                "company": company_ref,
                "body": company_note,
                "dry_run": request.dry_run,
            }
        )

    for idx, contact in enumerate(payload.get("contacts") or []):
        contact_note = contact.get("note")
        contact_id = ids.get(f"contact_{idx}")
        if not contact_note or not contact_id:
            continue
        note_id = f"{prefix}-contact-note-{uuid.uuid4().hex[:8]}"
        ids[f"contact_note_{idx}"] = note_id
        CRM_STORE["notes"].append(
            {
                "id": note_id,
                "contact_id": contact_id,
                "company": company_ref,
                "body": contact_note,
                "dry_run": request.dry_run,
            }
        )

    lead_dump = clean.model_dump()
    persist_store(CRM_STORE)
    lead_path = persist_upsert(
        lead=lead_dump,
        payload=payload,
        hubspot_ids=ids,
        dry_run=request.dry_run,
    )
    logger.info("HubSpot mock wrote lead to %s", lead_path)

    return clean.model_copy(
        update={"hubspot_ids": ids, "status": LeadStatus.PUBLISHED},
    )


app = FastAPI(title="hubspot-mock", version="0.1.0")
app.add_middleware(RequestResponseLogMiddleware, service_name="hubspot-mock")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hubspot-mock"}


app.include_router(router)
