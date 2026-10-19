"""CampaignRun persistence."""

from __future__ import annotations

import uuid
from typing import Any

from botocore.exceptions import ClientError

from services.api.db import campaign_runs_table
from services.api.dynamo_utils import from_dynamo
from services.api.models import utc_now_iso
from services.api.schemas.entities import CampaignRunPublic, RunStatus, RunTrigger


class CampaignRunNotFoundError(Exception):
    pass


def _to_public(item: dict[str, Any]) -> CampaignRunPublic:
    cleaned = from_dynamo(item)
    return CampaignRunPublic(
        run_id=cleaned["run_id"],
        campaign_id=cleaned["campaign_id"],
        campaign_name=cleaned["campaign_name"],
        trigger=RunTrigger(cleaned["trigger"]),
        status=RunStatus(cleaned["status"]),
        started_at=cleaned.get("started_at"),
        ended_at=cleaned.get("ended_at"),
        lh_wf_run_id=cleaned.get("lh_wf_run_id"),
        result_summary=cleaned.get("result_summary"),
        created_at=cleaned["created_at"],
        updated_at=cleaned["updated_at"],
    )


def create_run(
    *,
    campaign_id: str,
    campaign_name: str,
    trigger: RunTrigger,
    status: RunStatus = RunStatus.PENDING,
    lh_wf_run_id: str | None = None,
) -> CampaignRunPublic:
    now = utc_now_iso()
    item: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "trigger": str(trigger),
        "status": str(status),
        "created_at": now,
        "updated_at": now,
    }
    if status == RunStatus.RUNNING:
        item["started_at"] = now
    if lh_wf_run_id:
        item["lh_wf_run_id"] = lh_wf_run_id
    campaign_runs_table().put_item(Item=item)
    return _to_public(item)


def get_run(run_id: str) -> CampaignRunPublic | None:
    resp = campaign_runs_table().get_item(Key={"run_id": run_id})
    item = resp.get("Item")
    return _to_public(item) if item else None


def require_run(run_id: str) -> CampaignRunPublic:
    run = get_run(run_id)
    if run is None:
        raise CampaignRunNotFoundError(run_id)
    return run


def list_runs_for_campaign(campaign_id: str, *, limit: int = 50) -> list[CampaignRunPublic]:
    resp = campaign_runs_table().query(
        IndexName="campaign_id-created_at-index",
        KeyConditionExpression="campaign_id = :c",
        ExpressionAttributeValues={":c": campaign_id},
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_to_public(i) for i in (resp.get("Items") or [])]


def mark_running(run_id: str, *, lh_wf_run_id: str) -> CampaignRunPublic:
    now = utc_now_iso()
    try:
        resp = campaign_runs_table().update_item(
            Key={"run_id": run_id},
            UpdateExpression=(
                "SET #status = :status, started_at = :started, "
                "lh_wf_run_id = :lh, updated_at = :u"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": str(RunStatus.RUNNING),
                ":started": now,
                ":lh": lh_wf_run_id,
                ":u": now,
            },
            ConditionExpression="attribute_exists(run_id)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CampaignRunNotFoundError(run_id) from exc
        raise
    return _to_public(resp["Attributes"])


def complete_run(
    run_id: str,
    *,
    status: RunStatus,
    result_summary: dict[str, Any] | None = None,
    lh_wf_run_id: str | None = None,
) -> CampaignRunPublic:
    now = utc_now_iso()
    parts = ["#status = :status", "ended_at = :ended", "updated_at = :u"]
    values: dict[str, Any] = {
        ":status": str(status),
        ":ended": now,
        ":u": now,
    }
    if result_summary is not None:
        parts.append("result_summary = :summary")
        values[":summary"] = result_summary
    if lh_wf_run_id is not None:
        parts.append("lh_wf_run_id = :lh")
        values[":lh"] = lh_wf_run_id
    try:
        resp = campaign_runs_table().update_item(
            Key={"run_id": run_id},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(run_id)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CampaignRunNotFoundError(run_id) from exc
        raise
    return _to_public(resp["Attributes"])


def credit_published_companies(run_id: str, published: int) -> int:
    """Remember how many HubSpot upserts this run has already added to the campaign.

    Returns the newly credited count. A repeated completion of the same run
    returns 0 once that count has been applied.
    """
    if published <= 0:
        return 0
    resp = campaign_runs_table().get_item(Key={"run_id": run_id})
    item = from_dynamo(resp.get("Item") or {})
    if not item:
        raise CampaignRunNotFoundError(run_id)
    previous = int(item.get("companies_counted") or 0)
    if published <= previous:
        return 0
    try:
        campaign_runs_table().update_item(
            Key={"run_id": run_id},
            UpdateExpression="SET companies_counted = :published, updated_at = :u",
            ExpressionAttributeValues={
                ":published": published,
                ":prev": previous,
                ":u": utc_now_iso(),
            },
            ConditionExpression=(
                "attribute_exists(run_id) AND "
                "(attribute_not_exists(companies_counted) OR companies_counted = :prev)"
            ),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return 0
        raise
    return published - previous


def append_lead_outcome(run_id: str, outcome: dict[str, Any]) -> None:
    now = utc_now_iso()
    try:
        campaign_runs_table().update_item(
            Key={"run_id": run_id},
            UpdateExpression=(
                "SET lead_outcomes = list_append(if_not_exists(lead_outcomes, :empty), :vals), "
                "updated_at = :u"
            ),
            ExpressionAttributeValues={
                ":empty": [],
                ":vals": [outcome],
                ":u": now,
            },
            ConditionExpression="attribute_exists(run_id)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CampaignRunNotFoundError(run_id) from exc
        raise


def list_lead_outcomes(run_id: str) -> list[dict[str, Any]]:
    resp = campaign_runs_table().get_item(Key={"run_id": run_id})
    item = resp.get("Item") or {}
    raw = from_dynamo(item).get("lead_outcomes") or []
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
