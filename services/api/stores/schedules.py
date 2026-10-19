"""Schedule persistence (LittleHorse schedule id filled in Phase 5)."""

from __future__ import annotations

import uuid
from typing import Any

from botocore.exceptions import ClientError

from services.api.db import schedules_table
from services.api.models import utc_now_iso
from services.api.schemas.entities import SchedulePublic, ScheduleType


class ScheduleNotFoundError(Exception):
    pass


def _to_public(item: dict[str, Any]) -> SchedulePublic:
    return SchedulePublic(
        schedule_id=item["schedule_id"],
        campaign_id=item["campaign_id"],
        type=ScheduleType(item["type"]),
        expression=item["expression"],
        timezone=item.get("timezone") or "UTC",
        enabled=bool(item.get("enabled", True)),
        lh_schedule_id=item.get("lh_schedule_id") or None,
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )


def create_schedule(
    *,
    campaign_id: str,
    type: ScheduleType,
    expression: str,
    timezone: str,
    enabled: bool,
) -> SchedulePublic:
    now = utc_now_iso()
    item: dict[str, Any] = {
        "schedule_id": str(uuid.uuid4()),
        "campaign_id": campaign_id,
        "type": str(type),
        "expression": expression.strip(),
        "timezone": timezone.strip() or "UTC",
        "enabled": enabled,
        "created_at": now,
        "updated_at": now,
    }
    schedules_table().put_item(Item=item)
    return _to_public(item)


def get_schedule(schedule_id: str) -> SchedulePublic | None:
    resp = schedules_table().get_item(Key={"schedule_id": schedule_id})
    item = resp.get("Item")
    return _to_public(item) if item else None


def require_schedule(schedule_id: str) -> SchedulePublic:
    schedule = get_schedule(schedule_id)
    if schedule is None:
        raise ScheduleNotFoundError(schedule_id)
    return schedule


def list_schedules_for_campaign(campaign_id: str) -> list[SchedulePublic]:
    resp = schedules_table().query(
        IndexName="campaign_id-index",
        KeyConditionExpression="campaign_id = :c",
        ExpressionAttributeValues={":c": campaign_id},
    )
    return [_to_public(i) for i in (resp.get("Items") or [])]


def update_schedule(
    schedule_id: str,
    *,
    expression: str | None = None,
    timezone: str | None = None,
    enabled: bool | None = None,
    lh_schedule_id: str | None = None,
) -> SchedulePublic:
    parts = ["updated_at = :u"]
    values: dict[str, Any] = {":u": utc_now_iso()}
    if expression is not None:
        parts.append("expression = :expression")
        values[":expression"] = expression.strip()
    if timezone is not None:
        parts.append("timezone = :timezone")
        values[":timezone"] = timezone.strip() or "UTC"
    if enabled is not None:
        parts.append("enabled = :enabled")
        values[":enabled"] = enabled
    remove_parts: list[str] = []
    if lh_schedule_id is not None:
        if lh_schedule_id:
            parts.append("lh_schedule_id = :lh")
            values[":lh"] = lh_schedule_id
        else:
            remove_parts.append("lh_schedule_id")
    update_expr = "SET " + ", ".join(parts)
    if remove_parts:
        update_expr += " REMOVE " + ", ".join(remove_parts)
    try:
        resp = schedules_table().update_item(
            Key={"schedule_id": schedule_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(schedule_id)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ScheduleNotFoundError(schedule_id) from exc
        raise
    return _to_public(resp["Attributes"])


def delete_schedule(schedule_id: str) -> None:
    require_schedule(schedule_id)
    schedules_table().delete_item(Key={"schedule_id": schedule_id})
