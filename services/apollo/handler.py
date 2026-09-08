from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.apollo.client import (
    ApolloConfigError,
    find_decision_makers as apollo_find_decision_makers,
    search_companies as apollo_search_companies,
)
from services.common.icp import load_icp
from services.common.limits import max_contacts_per_company
from services.common.schemas import Company, CompanySearchRequest, Contact

router = APIRouter(prefix="/v1", tags=["apollo"])


class FindDecisionMakersRequest(BaseModel):
    company: Company
    icp_version: str | None = None
    titles: list[str] | None = None
    max_results: int = Field(default_factory=lambda: max_contacts_per_company(10), ge=1, le=50)


@router.post("/search-companies")
def search_companies(request: CompanySearchRequest) -> list[Company]:
    """Search Apollo for companies matching ICP hard filters."""
    try:
        icp = load_icp()
        if request.icp_version and request.icp_version != icp.version:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown icp_version {request.icp_version!r}; loaded {icp.version!r}",
            )
        return apollo_search_companies(icp, request.segment_ids, request.max_results)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApolloConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/find-decision-makers")
def find_decision_makers(request: FindDecisionMakersRequest) -> list[Contact]:
    """Find buyer-persona contacts at a company (public fields only)."""
    try:
        icp = load_icp()
        if request.icp_version and request.icp_version != icp.version:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown icp_version {request.icp_version!r}; loaded {icp.version!r}",
            )
        contacts = apollo_find_decision_makers(
            icp,
            request.company,
            titles=request.titles,
            max_results=request.max_results,
        )
        return contacts
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApolloConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
