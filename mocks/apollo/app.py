"""Mock Apollo microservice — same HTTP contract as services/apollo."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mocks.common.logging import RequestResponseLogMiddleware, configure_logging
from mocks.data.fixtures import companies_for_segments, contacts_for_company
from services.common.icp import load_icp
from services.common.limits import max_contacts_per_company
from services.common.schemas import Company, CompanySearchRequest, Contact

configure_logging()
router = APIRouter(prefix="/v1", tags=["apollo-mock"])


class FindDecisionMakersRequest(BaseModel):
    company: Company
    icp_version: str | None = None
    titles: list[str] | None = None
    max_results: int = Field(default_factory=lambda: max_contacts_per_company(10), ge=1, le=50)


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "apollo-mock", "status": "ok"}


@router.post("/search-companies")
def search_companies(request: CompanySearchRequest) -> list[Company]:
    icp = load_icp()
    if request.icp_version and request.icp_version != icp.version:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown icp_version {request.icp_version!r}; loaded {icp.version!r}",
        )
    for segment_id in request.segment_ids:
        try:
            icp.segment_by_id(segment_id)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return companies_for_segments(request.segment_ids, request.max_results)


@router.post("/find-decision-makers")
def find_decision_makers(request: FindDecisionMakersRequest) -> list[Contact]:
    icp = load_icp()
    if request.icp_version and request.icp_version != icp.version:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown icp_version {request.icp_version!r}; loaded {icp.version!r}",
        )
    contacts = contacts_for_company(request.company)
    return contacts[: request.max_results]


app = FastAPI(title="apollo-mock", version="0.1.0")
app.add_middleware(RequestResponseLogMiddleware, service_name="apollo-mock")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "apollo-mock"}


app.include_router(router)
