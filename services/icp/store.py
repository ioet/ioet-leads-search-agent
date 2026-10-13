"""S3 (or local) persistence for icp.json and source PDFs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.common.icp import DEFAULT_ICP_PATH, clear_icp_s3_cache

LOCAL_CACHE_DIR = Path(".cache/icp-admin")
DEFAULT_ICP_KEY = "icp/icp.json"


class IcpStoreError(RuntimeError):
    pass


def _bucket() -> str:
    return os.environ.get("ICP_S3_BUCKET", "").strip()


def _icp_key() -> str:
    return os.environ.get("ICP_S3_KEY", "").strip() or DEFAULT_ICP_KEY


def uses_s3() -> bool:
    return bool(_bucket())


def _client():
    import boto3

    return boto3.client("s3")


def safe_filename(name: str) -> str:
    base = Path(name or "").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned or 'icp'}.pdf"
    return cleaned[:120]


def get_current_icp() -> tuple[dict[str, Any], str | None, str | None]:
    """Return (icp_dict, s3_version_id, last_modified_iso)."""
    if uses_s3():
        obj = _client().get_object(Bucket=_bucket(), Key=_icp_key())
        raw = json.loads(obj["Body"].read().decode("utf-8"))
        version_id = obj.get("VersionId")
        last_modified = obj.get("LastModified")
        modified = (
            last_modified.astimezone(timezone.utc).isoformat()
            if last_modified is not None
            else None
        )
        return raw, version_id, modified

    path = DEFAULT_ICP_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return raw, None, mtime


def put_icp(icp: dict[str, Any], *, upload_id: str | None, source_filename: str | None) -> str | None:
    body = json.dumps(icp, indent=2, ensure_ascii=False).encode("utf-8")
    version = str(icp.get("version") or "unknown")
    filename = safe_filename(source_filename or "icp.pdf")

    if uses_s3():
        client = _client()
        result = client.put_object(
            Bucket=_bucket(),
            Key=_icp_key(),
            Body=body,
            ContentType="application/json",
        )
        if upload_id:
            dest_key = f"icp/sources/{version}/{filename}"
            client.copy_object(
                Bucket=_bucket(),
                CopySource={"Bucket": _bucket(), "Key": _upload_key(upload_id)},
                Key=dest_key,
                MetadataDirective="COPY",
            )
        clear_icp_s3_cache()
        version_id = result.get("VersionId")
        return str(version_id) if version_id else None

    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_CACHE_DIR / "icp.json").write_bytes(body)
    return None


def save_upload(pdf_bytes: bytes, filename: str) -> str:
    upload_id = str(uuid4())
    if uses_s3():
        _client().put_object(
            Bucket=_bucket(),
            Key=_upload_key(upload_id),
            Body=pdf_bytes,
            ContentType="application/pdf",
            Metadata={"filename": safe_filename(filename)},
        )
        return upload_id

    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = LOCAL_CACHE_DIR / f"{upload_id}.pdf"
    dest.write_bytes(pdf_bytes)
    (LOCAL_CACHE_DIR / f"{upload_id}.name").write_text(safe_filename(filename), encoding="utf-8")
    return upload_id


def _upload_key(upload_id: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", upload_id):
        raise IcpStoreError("Invalid upload_id")
    return f"icp/uploads/{upload_id}.pdf"


def read_upload_bytes(upload_id: str) -> bytes:
    """Used by tests / local; not required on the publish path (S3 copy)."""
    if uses_s3():
        obj = _client().get_object(Bucket=_bucket(), Key=_upload_key(upload_id))
        return obj["Body"].read()
    path = LOCAL_CACHE_DIR / f"{upload_id}.pdf"
    if not path.is_file():
        raise IcpStoreError(f"Unknown upload_id {upload_id}")
    return path.read_bytes()
