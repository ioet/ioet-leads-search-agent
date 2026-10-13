from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError

from services.agent.bedrock import BedrockConfigError, BedrockResponseError
from services.common.icp import IdealCustomerProfile
from services.icp.extract import extract_icp_from_text, pdf_to_text
from services.icp.store import (
    IcpStoreError,
    get_current_icp,
    put_icp,
    save_upload,
)

router = APIRouter(prefix="/v1", tags=["icp"])

MAX_PDF_BYTES = 5 * 1024 * 1024


class PutIcpRequest(BaseModel):
    icp: dict[str, Any]
    upload_id: str | None = None
    source_filename: str | None = None


class ValidateIcpRequest(BaseModel):
    icp: dict[str, Any]


def _validation_errors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        IdealCustomerProfile.model_validate(payload)
        return []
    except ValidationError as exc:
        return list(exc.errors())


@router.get("/icp")
def get_icp() -> dict[str, Any]:
    try:
        icp, version_id, last_modified = get_current_icp()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"ICP not found: {exc}") from exc
    return {
        "icp": icp,
        "s3_version_id": version_id,
        "last_modified": last_modified,
        "errors": _validation_errors(icp) if isinstance(icp, dict) else [],
    }


@router.post("/icp/extract")
async def extract_icp(file: UploadFile = File(...)) -> dict[str, Any]:
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

    current: dict[str, Any] | None = None
    try:
        current, _, _ = get_current_icp()
    except Exception:
        current = None

    try:
        candidate, errors = extract_icp_from_text(
            text, source_filename=filename, current_icp=current
        )
        upload_id = save_upload(pdf_bytes, filename)
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


@router.post("/icp/validate")
def validate_icp(request: ValidateIcpRequest) -> dict[str, Any]:
    errors = _validation_errors(request.icp)
    return {"ok": not errors, "errors": errors, "icp": request.icp}


@router.put("/icp")
def publish_icp(request: PutIcpRequest) -> dict[str, Any]:
    try:
        icp = IdealCustomerProfile.model_validate(request.icp)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    payload = icp.model_dump(mode="json")
    try:
        version_id = put_icp(
            payload,
            upload_id=request.upload_id,
            source_filename=request.source_filename or payload.get("source"),
        )
    except IcpStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"S3 write failed: {exc}") from exc

    return {
        "icp": payload,
        "s3_version_id": version_id,
        "errors": [],
    }
