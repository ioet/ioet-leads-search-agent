"""Auth endpoints: signup, verify, login, refresh, logout, me."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from services.api import settings
from services.api.auth.cookies import clear_auth_cookies, set_auth_cookies
from services.api.auth.deps import current_user, to_public
from services.api.auth.email import send_verification_email
from services.api.auth.passwords import hash_password, verify_password
from services.api.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from services.api.models import (
    LoginRequest,
    MessageResponse,
    SignupRequest,
    UserPublic,
    UserRecord,
    UserRole,
    UserStatus,
)
from services.api.stores import refresh_tokens as refresh_store
from services.api.stores import users as user_store
from services.api.stores.users import EmailAlreadyExistsError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _email_allowed(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain == settings.allowed_email_domain()


def _issue_session(response: Response, user: UserRecord) -> UserPublic:
    access = create_access_token(user_id=user.user_id, email=user.email, role=user.role)
    refresh = generate_refresh_token()
    refresh_store.store_refresh_token(raw_token=refresh, user_id=user.user_id)
    set_auth_cookies(response, access_token=access, refresh_token=refresh)
    return to_public(user)


@router.post("/signup", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest) -> MessageResponse:
    if not _email_allowed(body.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email must be @{settings.allowed_email_domain()}",
        )
    raw_verify = secrets.token_urlsafe(32)
    try:
        user_store.create_user_if_email_free(
            email=body.email,
            password_hash=hash_password(body.password),
            role=UserRole.MEMBER,
            status=UserStatus.PENDING_VERIFICATION,
            verification_token_hash=hash_refresh_token(raw_verify),
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc

    send_verification_email(email=body.email, raw_token=raw_verify)
    return MessageResponse(
        message="Check your email to verify your account before signing in.",
    )


@router.post("/verify", response_model=MessageResponse)
def verify_email(token: Annotated[str, Query(min_length=1)]) -> MessageResponse:
    if not token.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing token")
    user = user_store.get_user_by_verification_token_hash(hash_refresh_token(token))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    if user.status == UserStatus.ACTIVE:
        return MessageResponse(message="Email already verified.")
    user_store.mark_email_verified(user.user_id)
    return MessageResponse(message="Email verified. You can sign in.")


@router.post("/login", response_model=UserPublic)
def login(body: LoginRequest, response: Response) -> UserPublic:
    user = user_store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email before signing in",
        )
    return _issue_session(response, user)


@router.post("/refresh", response_model=UserPublic)
def refresh(request: Request, response: Response) -> UserPublic:
    raw = request.cookies.get(settings.refresh_cookie_name())
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    stored = refresh_store.get_refresh_token(raw)
    if stored is None:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user = user_store.get_user(str(stored["user_id"]))
    if user is None or user.status != UserStatus.ACTIVE:
        refresh_store.delete_refresh_token(raw)
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    new_refresh = generate_refresh_token()
    refresh_store.rotate_refresh_token(
        old_raw_token=raw,
        new_raw_token=new_refresh,
        user_id=user.user_id,
    )
    access = create_access_token(user_id=user.user_id, email=user.email, role=user.role)
    set_auth_cookies(response, access_token=access, refresh_token=new_refresh)
    return to_public(user)


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response) -> MessageResponse:
    raw = request.cookies.get(settings.refresh_cookie_name())
    if raw:
        refresh_store.delete_refresh_token(raw)
    clear_auth_cookies(response)
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=UserPublic)
def me(user: Annotated[UserRecord, Depends(current_user)]) -> UserPublic:
    return to_public(user)
