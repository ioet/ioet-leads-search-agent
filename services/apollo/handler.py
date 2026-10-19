from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.apollo.client import (
    ApolloConfigError,
    find_decision_makers as apollo_find_decision_makers,
    search_companies as apollo_search_companies,
)
from services.common.campaign_config import parse_campaign_config, persona_titles
from services.common.icp_ref import load_icp_for_request
from services.common.limits import max_contacts_per_company
from services.common.schemas import Company, CompanySearchRequest, Contact

router = APIRouter(prefix="/v1", tags=["apollo"])


class FindDecisionMakersRequest(BaseModel):
    company: Company
    icp_version: str | None = None
    icp_ref: str | None = None
    titles: list[str] | None = None
    max_results: int | None = None
    campaign_config: dict[str, Any] | None = None


@router.post("/search-companies")
def search_companies(request: CompanySearchRequest) -> list[Company]:
    """Search Apollo for companies matching ICP hard filters (+ campaign overrides)."""
    try:
        icp = load_icp_for_request(
            icp_ref=request.icp_ref, icp_version=request.icp_version
        )
        cfg = parse_campaign_config(request.campaign_config)
        return apollo_search_companies(
            icp,
            request.segment_ids,
            request.max_results,
            company_filter=cfg.companies_filter_config,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApolloConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/find-decision-makers")
def find_decision_makers(request: FindDecisionMakersRequest) -> list[Contact]:
    """Find buyer-persona contacts at a company (public fields only)."""
    try:
        icp = load_icp_for_request(
            icp_ref=request.icp_ref, icp_version=request.icp_version
        )
        cfg = parse_campaign_config(request.campaign_config)
        dm = cfg.decision_makers_config
        titles = request.titles or persona_titles(dm)
        max_results = request.max_results
        if max_results is None:
            max_results = dm.contacts_per_company or max_contacts_per_company()
        contacts = apollo_find_decision_makers(
            icp,
            request.company,
            titles=titles,
            max_results=max_results,
        )
        if dm.skip_when_no_email:
            contacts = [c for c in contacts if c.email]
        if dm.email_requirement == "verified_only":
            # Enrichment already drops locked placeholders; keep non-empty emails only.
            contacts = [c for c in contacts if c.email]
        return contacts[:max_results]
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApolloConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
