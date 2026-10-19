"""Object storage for ICP PDFs and JSON (S3 or local filesystem).

DynamoDB stores only URI references; callers load content via these helpers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.api import settings
from services.icp.store import IcpStoreError, safe_filename

LOCAL_ROOT = Path(".cache/api-icps")


def _bucket() -> str:
    return settings.icp_files_bucket()


def uses_s3() -> bool:
    return bool(_bucket())


def _s3():
    import boto3

    return boto3.client("s3", region_name=settings.aws_region())


def _pdf_key(icp_id: str, filename: str) -> str:
    return f"icps/{icp_id}/{safe_filename(filename)}"


def _json_key(icp_id: str) -> str:
    return f"icps/{icp_id}/icp.json"


def _upload_key(upload_id: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", upload_id):
        raise IcpStoreError("Invalid upload_id")
    return f"icps/uploads/{upload_id}.pdf"


def uri_for_s3_key(key: str) -> str:
    return f"s3://{_bucket()}/{key}"


def uri_for_local(rel: str) -> str:
    return f"local://{rel}"


def save_temp_upload(pdf_bytes: bytes, filename: str) -> str:
    upload_id = str(uuid4())
    if uses_s3():
        _s3().put_object(
            Bucket=_bucket(),
            Key=_upload_key(upload_id),
            Body=pdf_bytes,
            ContentType="application/pdf",
            Metadata={"filename": safe_filename(filename)},
        )
        return upload_id

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    (LOCAL_ROOT / f"{upload_id}.pdf").write_bytes(pdf_bytes)
    (LOCAL_ROOT / f"{upload_id}.name").write_text(safe_filename(filename), encoding="utf-8")
    return upload_id


def read_temp_upload(upload_id: str) -> tuple[bytes, str]:
    if uses_s3():
        obj = _s3().get_object(Bucket=_bucket(), Key=_upload_key(upload_id))
        filename = (obj.get("Metadata") or {}).get("filename") or "icp.pdf"
        return obj["Body"].read(), filename

    path = LOCAL_ROOT / f"{upload_id}.pdf"
    if not path.is_file():
        raise IcpStoreError(f"Unknown upload_id {upload_id}")
    name_path = LOCAL_ROOT / f"{upload_id}.name"
    filename = name_path.read_text(encoding="utf-8") if name_path.is_file() else "icp.pdf"
    return path.read_bytes(), filename


def persist_icp_files(
    *,
    icp_id: str,
    icp_json: dict[str, Any],
    upload_id: str | None,
    source_filename: str | None,
) -> tuple[str | None, str]:
    """Write JSON (+ optional PDF) and return (pdf_uri, json_uri)."""
    body = json.dumps(icp_json, indent=2, ensure_ascii=False).encode("utf-8")
    filename = safe_filename(source_filename or "icp.pdf")

    if uses_s3():
        client = _s3()
        json_key = _json_key(icp_id)
        client.put_object(
            Bucket=_bucket(),
            Key=json_key,
            Body=body,
            ContentType="application/json",
        )
        pdf_uri: str | None = None
        if upload_id:
            pdf_key = _pdf_key(icp_id, filename)
            client.copy_object(
                Bucket=_bucket(),
                CopySource={"Bucket": _bucket(), "Key": _upload_key(upload_id)},
                Key=pdf_key,
                MetadataDirective="COPY",
            )
            pdf_uri = uri_for_s3_key(pdf_key)
        return pdf_uri, uri_for_s3_key(json_key)

    dest_dir = LOCAL_ROOT / icp_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "icp.json").write_bytes(body)
    pdf_uri = None
    if upload_id:
        pdf_bytes, name = read_temp_upload(upload_id)
        pdf_name = safe_filename(source_filename or name)
        (dest_dir / pdf_name).write_bytes(pdf_bytes)
        pdf_uri = uri_for_local(f"{icp_id}/{pdf_name}")
    return pdf_uri, uri_for_local(f"{icp_id}/icp.json")


def load_json_uri(uri: str) -> dict[str, Any]:
    raw = _read_bytes(uri)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise IcpStoreError("ICP JSON must be an object")
    return data


def _read_bytes(uri: str) -> bytes:
    if uri.startswith("s3://"):
        without = uri[len("s3://") :]
        bucket, _, key = without.partition("/")
        if not bucket or not key:
            raise IcpStoreError(f"Invalid S3 URI: {uri}")
        return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    if uri.startswith("local://"):
        rel = uri[len("local://") :]
        path = LOCAL_ROOT / rel
        if not path.is_file():
            raise IcpStoreError(f"Missing local object: {uri}")
        return path.read_bytes()
    raise IcpStoreError(f"Unsupported URI scheme: {uri}")


def delete_icp_files(icp_id: str, *, pdf_uri: str | None, json_uri: str) -> None:
    if uses_s3():
        client = _s3()
        for uri in (pdf_uri, json_uri):
            if not uri or not uri.startswith("s3://"):
                continue
            without = uri[len("s3://") :]
            bucket, _, key = without.partition("/")
            if bucket and key:
                client.delete_object(Bucket=bucket, Key=key)
        return
    dest_dir = LOCAL_ROOT / icp_id
    if dest_dir.is_dir():
        for child in dest_dir.iterdir():
            child.unlink(missing_ok=True)
        dest_dir.rmdir()
