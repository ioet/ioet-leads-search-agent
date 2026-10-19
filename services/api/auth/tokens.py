"""JWT access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from services.api import settings
from services.api.models import UserRole


class TokenError(Exception):
    """Raised when a token is missing, expired, or invalid."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(*, user_id: str, email: str, role: UserRole) -> str:
    exp = _now() + timedelta(seconds=settings.access_token_ttl_seconds())
    payload = {
        "sub": user_id,
        "email": email,
        "role": str(role),
        "type": "access",
        "exp": exp,
        "iat": _now(),
    }
    return jwt.encode(payload, settings.jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired access token") from exc
    if payload.get("type") != "access":
        raise TokenError("Invalid access token type")
    if not payload.get("sub"):
        raise TokenError("Access token missing subject")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry_iso() -> str:
    exp = _now() + timedelta(seconds=settings.refresh_token_ttl_seconds())
    return exp.replace(microsecond=0).isoformat().replace("+00:00", "Z")
