"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from services.api import settings
from services.api.auth.tokens import TokenError, decode_access_token
from services.api.models import UserPublic, UserRecord, UserRole, UserStatus
from services.api.stores import users as user_store


def to_public(user: UserRecord) -> UserPublic:
    return UserPublic(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        email_verified_at=user.email_verified_at,
    )


def current_user(request: Request) -> UserRecord:
    token = request.cookies.get(settings.access_cookie_name())
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    user = user_store.get_user(str(payload["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )
    return user


def current_user_public(user: Annotated[UserRecord, Depends(current_user)]) -> UserPublic:
    return to_public(user)


def require_admin(user: Annotated[UserRecord, Depends(current_user)]) -> UserRecord:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
