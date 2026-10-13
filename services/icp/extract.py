"""PDF text extraction + Bedrock mapping onto IdealCustomerProfile JSON."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from pydantic import ValidationError

from services.agent.bedrock import BedrockClient, BedrockResponseError
from services.agent.prompts import extract_icp_system, extract_icp_user
from services.common.icp import IdealCustomerProfile

logger = logging.getLogger(__name__)

MAX_PDF_CHARS = 20_000


def pdf_to_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n\n".join(part.strip() for part in pages if part and part.strip())
    if not text:
        raise ValueError("PDF contained no extractable text")
    if len(text) > MAX_PDF_CHARS:
        logger.warning("Truncating PDF text from %d to %d chars", len(text), MAX_PDF_CHARS)
        return text[:MAX_PDF_CHARS]
    return text


def extract_icp_from_text(
    pdf_text: str,
    *,
    source_filename: str,
    current_icp: dict[str, Any] | None = None,
    bedrock: BedrockClient | None = None,
    model_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (candidate_dict, pydantic_error_list). Candidate may be partial."""
    client = bedrock or BedrockClient(model_id=model_id, complexity="high")
    raw = client.converse_json(
        extract_icp_system(),
        extract_icp_user(pdf_text, source_filename=source_filename, current_icp=current_icp),
        max_tokens=8192,
    )
    if not isinstance(raw, dict):
        raise BedrockResponseError(f"ICP extract response must be object, got {type(raw)!r}")

    raw.setdefault("source", source_filename)
    errors: list[dict[str, Any]] = []
    try:
        icp = IdealCustomerProfile.model_validate(raw)
        return icp.model_dump(mode="json"), []
    except ValidationError as exc:
        errors = exc.errors()
        logger.info("Extracted ICP failed validation (%d errors)", len(errors))
        return raw, errors
