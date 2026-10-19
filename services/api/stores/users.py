"""User persistence in DynamoDB."""

from __future__ import annotations

import uuid
from typing import Any

from botocore.exceptions import ClientError

from services.api.db import users_table
from services.api.models import UserRecord, UserRole, UserStatus, utc_now_iso


class UserStoreError(Exception):
    pass


class EmailAlreadyExistsError(UserStoreError):
    pass


class UserNotFoundError(UserStoreError):
    pass


def _item_to_user(item: dict[str, Any]) -> UserRecord:
    return UserRecord.model_validate(item)


def create_user(
    *,
    email: str,
    password_hash: str,
    role: UserRole = UserRole.MEMBER,
    status: UserStatus = UserStatus.PENDING_VERIFICATION,
    verification_token_hash: str | None = None,
) -> UserRecord:
    """Insert a user. Caller must check email uniqueness first (see create_user_if_email_free)."""
    now = utc_now_iso()
    user_id = str(uuid.uuid4())
    item: dict[str, Any] = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "role": str(role),
        "status": str(status),
        "created_at": now,
        "updated_at": now,
    }
    if verification_token_hash:
        item["verification_token_hash"] = verification_token_hash
    users_table().put_item(Item=item)
    return _item_to_user(item)


def create_user_if_email_free(
    *,
    email: str,
    password_hash: str,
    role: UserRole = UserRole.MEMBER,
    status: UserStatus = UserStatus.PENDING_VERIFICATION,
    verification_token_hash: str | None = None,
) -> UserRecord:
    if get_user_by_email(email) is not None:
        raise EmailAlreadyExistsError(email)
    return create_user(
        email=email,
        password_hash=password_hash,
        role=role,
        status=status,
        verification_token_hash=verification_token_hash,
    )


def get_user(user_id: str) -> UserRecord | None:
    resp = users_table().get_item(Key={"user_id": user_id})
    item = resp.get("Item")
    return _item_to_user(item) if item else None


def get_user_by_email(email: str) -> UserRecord | None:
    resp = users_table().query(
        IndexName="email-index",
        KeyConditionExpression="email = :email",
        ExpressionAttributeValues={":email": email.strip().lower()},
        Limit=1,
    )
    items = resp.get("Items") or []
    if not items:
        return None
    return _item_to_user(items[0])


def get_user_by_verification_token_hash(token_hash: str) -> UserRecord | None:
    # Scan is acceptable at low user volume for Phase 1; add a GSI later if needed.
    resp = users_table().scan(
        FilterExpression="verification_token_hash = :h",
        ExpressionAttributeValues={":h": token_hash},
    )
    items = resp.get("Items") or []
    if not items:
        return None
    return _item_to_user(items[0])


def mark_email_verified(user_id: str) -> UserRecord:
    now = utc_now_iso()
    try:
        resp = users_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression=(
                "SET #status = :status, email_verified_at = :verified, "
                "updated_at = :updated REMOVE verification_token_hash"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": str(UserStatus.ACTIVE),
                ":verified": now,
                ":updated": now,
            },
            ConditionExpression="attribute_exists(user_id)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise UserNotFoundError(user_id) from exc
        raise
    return _item_to_user(resp["Attributes"])


def display_name(user: UserRecord) -> str:
    """Name stored on the user, or their email when no name is set."""
    if user.name and user.name.strip():
        return user.name.strip()
    return user.email


def list_users(*, limit: int = 100) -> list[UserRecord]:
    resp = users_table().scan(Limit=limit)
    items = resp.get("Items") or []
    return [_item_to_user(item) for item in items]


def update_user(
    user_id: str,
    *,
    role: UserRole | None = None,
    status: UserStatus | None = None,
) -> UserRecord:
    if role is None and status is None:
        user = get_user(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    parts: list[str] = ["updated_at = :updated"]
    values: dict[str, Any] = {":updated": utc_now_iso()}
    names: dict[str, str] = {}
    if role is not None:
        parts.append("#role = :role")
        values[":role"] = str(role)
        names["#role"] = "role"
    if status is not None:
        parts.append("#status = :status")
        values[":status"] = str(status)
        names["#status"] = "status"

    kwargs: dict[str, Any] = {
        "Key": {"user_id": user_id},
        "UpdateExpression": "SET " + ", ".join(parts),
        "ExpressionAttributeValues": values,
        "ConditionExpression": "attribute_exists(user_id)",
        "ReturnValues": "ALL_NEW",
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names
    try:
        resp = users_table().update_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise UserNotFoundError(user_id) from exc
        raise
    return _item_to_user(resp["Attributes"])
