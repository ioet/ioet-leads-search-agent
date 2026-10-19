"""ICP metadata persistence (JSON/PDF live in object storage)."""

from __future__ import annotations

import uuid
from typing import Any

from botocore.exceptions import ClientError

from services.api.db import icps_table
from services.api.models import utc_now_iso
from services.api.schemas.entities import IcpPublic
from services.api import storage


class IcpNotFoundError(Exception):
    pass


def _to_public(item: dict[str, Any]) -> IcpPublic:
    return IcpPublic.model_validate(item)


def create_icp(
    *,
    title: str,
    icp_json: dict[str, Any],
    created_by: str,
    upload_id: str | None,
    source_filename: str | None,
) -> IcpPublic:
    icp_id = str(uuid.uuid4())
    pdf_uri, json_uri = storage.persist_icp_files(
        icp_id=icp_id,
        icp_json=icp_json,
        upload_id=upload_id,
        source_filename=source_filename,
    )
    now = utc_now_iso()
    item = {
        "icp_id": icp_id,
        "title": title.strip(),
        "pdf_s3_uri": pdf_uri,
        "icp_json_s3_uri": json_uri,
        "version": str(icp_json.get("version") or ""),
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    # DynamoDB rejects None attributes
    if pdf_uri is None:
        item.pop("pdf_s3_uri", None)
    icps_table().put_item(Item=item)
    return _to_public(item)


def get_icp(icp_id: str) -> IcpPublic | None:
    resp = icps_table().get_item(Key={"icp_id": icp_id})
    item = resp.get("Item")
    return _to_public(item) if item else None


def require_icp(icp_id: str) -> IcpPublic:
    icp = get_icp(icp_id)
    if icp is None:
        raise IcpNotFoundError(icp_id)
    return icp


def list_icps(*, limit: int = 100) -> list[IcpPublic]:
    resp = icps_table().scan(Limit=limit)
    items = resp.get("Items") or []
    return [_to_public(i) for i in items]


def load_icp_document(icp_id: str) -> dict[str, Any]:
    meta = require_icp(icp_id)
    return storage.load_json_uri(meta.icp_json_s3_uri)


def update_icp_title(icp_id: str, title: str) -> IcpPublic:
    try:
        resp = icps_table().update_item(
            Key={"icp_id": icp_id},
            UpdateExpression="SET title = :t, updated_at = :u",
            ExpressionAttributeValues={":t": title.strip(), ":u": utc_now_iso()},
            ConditionExpression="attribute_exists(icp_id)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise IcpNotFoundError(icp_id) from exc
        raise
    return _to_public(resp["Attributes"])


def delete_icp(icp_id: str) -> None:
    meta = require_icp(icp_id)
    storage.delete_icp_files(
        icp_id,
        pdf_uri=meta.pdf_s3_uri,
        json_uri=meta.icp_json_s3_uri,
    )
    icps_table().delete_item(Key={"icp_id": icp_id})
