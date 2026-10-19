"""Admin user management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from services.api.auth.deps import current_user, require_admin, to_public
from services.api.models import UpdateUserRequest, UserPublic, UserRecord
from services.api.schemas.entities import UserDirectoryEntry
from services.api.stores import users as user_store
from services.api.stores.users import UserNotFoundError, display_name

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/directory", response_model=list[UserDirectoryEntry])
def list_user_directory(
    _: Annotated[UserRecord, Depends(current_user)],
) -> list[UserDirectoryEntry]:
    """Users any signed-in member can assign as a campaign owner."""
    entries = [
        UserDirectoryEntry(user_id=user.user_id, email=user.email, name=display_name(user))
        for user in user_store.list_users()
        if user.status.value == "active"
    ]
    entries.sort(key=lambda entry: entry.name.lower())
    return entries


@router.get("", response_model=list[UserPublic])
def list_users(
    _: Annotated[UserRecord, Depends(require_admin)],
) -> list[UserPublic]:
    return [to_public(u) for u in user_store.list_users()]


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(
    user_id: str,
    body: UpdateUserRequest,
    _: Annotated[UserRecord, Depends(require_admin)],
) -> UserPublic:
    try:
        updated = user_store.update_user(user_id, role=body.role, status=body.status)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from exc
    return to_public(updated)
