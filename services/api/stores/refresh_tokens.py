"""Refresh-token persistence (hashed) in DynamoDB."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from services.api.auth.tokens import hash_refresh_token, refresh_expiry_iso
from services.api.db import refresh_tokens_table
from services.api.models import utc_now_iso


def _parse_expiry(value: str) -> datetime:
    raw = value.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


def store_refresh_token(*, raw_token: str, user_id: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    refresh_tokens_table().put_item(
        Item={
            "token_hash": token_hash,
            "user_id": user_id,
            "expires_at": refresh_expiry_iso(),
            "created_at": utc_now_iso(),
        }
    )


def get_refresh_token(raw_token: str) -> dict[str, Any] | None:
    token_hash = hash_refresh_token(raw_token)
    resp = refresh_tokens_table().get_item(Key={"token_hash": token_hash})
    item = resp.get("Item")
    if not item:
        return None
    expires_at = _parse_expiry(str(item["expires_at"]))
    if expires_at < datetime.now(timezone.utc):
        delete_refresh_token(raw_token)
        return None
    return item


def delete_refresh_token(raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    refresh_tokens_table().delete_item(Key={"token_hash": token_hash})


def delete_refresh_token_hash(token_hash: str) -> None:
    refresh_tokens_table().delete_item(Key={"token_hash": token_hash})


def rotate_refresh_token(*, old_raw_token: str, new_raw_token: str, user_id: str) -> None:
    """Delete the old token and store the new one (best-effort atomicity)."""
    old_hash = hash_refresh_token(old_raw_token)
    try:
        refresh_tokens_table().delete_item(
            Key={"token_hash": old_hash},
            ConditionExpression="attribute_exists(token_hash)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Already gone — still issue a new token for this user.
    store_refresh_token(raw_token=new_raw_token, user_id=user_id)
