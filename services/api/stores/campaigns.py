"""Campaign persistence."""

from __future__ import annotations

import uuid
from typing import Any

from botocore.exceptions import ClientError

from services.api.db import campaigns_table
from services.api.dynamo_utils import from_dynamo
from services.api.models import utc_now_iso
from services.api.schemas.campaign_config import CampaignConfig
from services.api.schemas.entities import CampaignPublic, CampaignStatus


class CampaignNotFoundError(Exception):
    pass


def _to_public(item: dict[str, Any]) -> CampaignPublic:
    cleaned = from_dynamo(item)
    config_raw = cleaned.get("config") or {}
    return CampaignPublic(
        campaign_id=cleaned["campaign_id"],
        name=cleaned["name"],
        owner_user_id=cleaned["owner_user_id"],
        owner_name=cleaned.get("owner_name"),
        icp_id=cleaned["icp_id"],
        start_date=cleaned.get("start_date"),
        end_date=cleaned.get("end_date"),
        status=CampaignStatus(cleaned["status"]),
        config=CampaignConfig.model_validate(config_raw),
        companies_upserted=int(cleaned.get("companies_upserted") or 0),
        created_at=cleaned["created_at"],
        updated_at=cleaned["updated_at"],
    )


def create_campaign(
    *,
    name: str,
    owner_user_id: str,
    owner_name: str | None,
    icp_id: str,
    start_date: str | None,
    end_date: str | None,
    status: CampaignStatus,
    config: CampaignConfig,
) -> CampaignPublic:
    now = utc_now_iso()
    item: dict[str, Any] = {
        "campaign_id": str(uuid.uuid4()),
        "name": name.strip(),
        "owner_user_id": owner_user_id,
        "icp_id": icp_id,
        "status": str(status),
        "config": config.model_dump_storage(),
        "companies_upserted": 0,
        "created_at": now,
        "updated_at": now,
    }
    if owner_name:
        item["owner_name"] = owner_name
    if start_date:
        item["start_date"] = start_date
    if end_date:
        item["end_date"] = end_date
    campaigns_table().put_item(Item=item)
    return _to_public(item)


def get_campaign(campaign_id: str) -> CampaignPublic | None:
    resp = campaigns_table().get_item(Key={"campaign_id": campaign_id})
    item = resp.get("Item")
    return _to_public(item) if item else None


def require_campaign(campaign_id: str) -> CampaignPublic:
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(campaign_id)
    return campaign


def list_campaigns(*, limit: int = 100) -> list[CampaignPublic]:
    resp = campaigns_table().scan(Limit=limit)
    return [_to_public(i) for i in (resp.get("Items") or [])]


def update_campaign(
    campaign_id: str,
    *,
    name: str | None = None,
    owner_user_id: str | None = None,
    owner_name: str | None = None,
    icp_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: CampaignStatus | None = None,
    config: CampaignConfig | None = None,
    clear_end_date: bool = False,
) -> CampaignPublic:
    parts: list[str] = ["updated_at = :u"]
    values: dict[str, Any] = {":u": utc_now_iso()}
    if name is not None:
        parts.append("#name = :name")
        values[":name"] = name.strip()
    if owner_user_id is not None:
        parts.append("owner_user_id = :owner_user_id")
        values[":owner_user_id"] = owner_user_id
    if owner_name is not None:
        parts.append("owner_name = :owner_name")
        values[":owner_name"] = owner_name
    if icp_id is not None:
        parts.append("icp_id = :icp_id")
        values[":icp_id"] = icp_id
    if start_date is not None:
        parts.append("start_date = :start_date")
        values[":start_date"] = start_date
    if end_date is not None:
        parts.append("end_date = :end_date")
        values[":end_date"] = end_date
    if status is not None:
        parts.append("#status = :status")
        values[":status"] = str(status)
    if config is not None:
        parts.append("config = :config")
        values[":config"] = config.model_dump_storage()

    names: dict[str, str] = {}
    if name is not None:
        names["#name"] = "name"
    if status is not None:
        names["#status"] = "status"

    update_expr = "SET " + ", ".join(parts)
    if clear_end_date:
        update_expr += " REMOVE end_date"

    kwargs: dict[str, Any] = {
        "Key": {"campaign_id": campaign_id},
        "UpdateExpression": update_expr,
        "ExpressionAttributeValues": values,
        "ConditionExpression": "attribute_exists(campaign_id)",
        "ReturnValues": "ALL_NEW",
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names
    try:
        resp = campaigns_table().update_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CampaignNotFoundError(campaign_id) from exc
        raise
    return _to_public(resp["Attributes"])


def add_companies_upserted(campaign_id: str, count: int) -> None:
    """Add companies a finished run wrote to HubSpot. Does not stop the campaign."""
    if count <= 0:
        return
    try:
        campaigns_table().update_item(
            Key={"campaign_id": campaign_id},
            UpdateExpression="ADD companies_upserted :n SET updated_at = :u",
            ExpressionAttributeValues={":n": count, ":u": utc_now_iso()},
            ConditionExpression="attribute_exists(campaign_id)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CampaignNotFoundError(campaign_id) from exc
        raise


def delete_campaign(campaign_id: str) -> None:
    require_campaign(campaign_id)
    campaigns_table().delete_item(Key={"campaign_id": campaign_id})
