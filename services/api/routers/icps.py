"""ICP CRUD — metadata in DynamoDB; PDF/JSON in object storage."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError

from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.api.auth.deps import current_user
from services.api.models import UserRecord
from services.api.schemas.entities import IcpCreate, IcpPublic
from services.api import storage
from services.api.stores import icps as icp_store
from services.api.stores.icps import IcpNotFoundError
from services.common.icp import IdealCustomerProfile
from services.icp.extract import extract_icp_from_text, pdf_to_text
from services.icp.store import IcpStoreError

router = APIRouter(prefix="/icps", tags=["icps"])

MAX_PDF_BYTES = 5 * 1024 * 1024


class UpdateIcpTitleRequest(BaseModel):
    title: str


def _validation_errors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        IdealCustomerProfile.model_validate(payload)
        return []
    except ValidationError as exc:
        return list(exc.errors())


@router.get("", response_model=list[IcpPublic])
def list_icps(
    _: Annotated[UserRecord, Depends(current_user)],
) -> list[IcpPublic]:
    return icp_store.list_icps()


@router.get("/{icp_id}", response_model=IcpPublic)
def get_icp(
    icp_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> IcpPublic:
    try:
        return icp_store.require_icp(icp_id)
    except IcpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="ICP not found") from exc


@router.get("/{icp_id}/document")
def get_icp_document(
    icp_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> dict[str, Any]:
    try:
        doc = icp_store.load_icp_document(icp_id)
    except IcpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="ICP not found") from exc
    except IcpStoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"icp": doc, "errors": _validation_errors(doc)}


@router.post("/extract")
async def extract_icp(
    _: Annotated[UserRecord, Depends(current_user)],
    file: UploadFile = File(...),
) -> dict[str, Any]:
    filename = file.filename or "icp.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds {MAX_PDF_BYTES // (1024 * 1024)} MB limit",
        )
    try:
        text = pdf_to_text(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc

    try:
        candidate, errors = extract_icp_from_text(
            text, source_filename=filename, current_icp=None
        )
        upload_id = storage.save_temp_upload(pdf_bytes, filename)
    except BedrockConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BedrockResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except IcpStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "icp": candidate,
        "errors": errors,
        "upload_id": upload_id,
        "source_filename": filename,
    }


@router.post("", response_model=IcpPublic, status_code=status.HTTP_201_CREATED)
def create_icp(
    body: IcpCreate,
    user: Annotated[UserRecord, Depends(current_user)],
) -> IcpPublic:
    try:
        IdealCustomerProfile.model_validate(body.icp)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    try:
        return icp_store.create_icp(
            title=body.title,
            icp_json=body.icp,
            created_by=user.user_id,
            upload_id=body.upload_id,
            source_filename=body.source_filename,
        )
    except IcpStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Storage write failed: {exc}") from exc


@router.patch("/{icp_id}", response_model=IcpPublic)
def update_icp(
    icp_id: str,
    body: UpdateIcpTitleRequest,
    _: Annotated[UserRecord, Depends(current_user)],
) -> IcpPublic:
    try:
        return icp_store.update_icp_title(icp_id, body.title)
    except IcpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="ICP not found") from exc


@router.delete("/{icp_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_icp(
    icp_id: str,
    _: Annotated[UserRecord, Depends(current_user)],
) -> None:
    try:
        icp_store.delete_icp(icp_id)
    except IcpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="ICP not found") from exc
