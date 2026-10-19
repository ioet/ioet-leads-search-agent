"""HTTP cookie helpers for access + refresh tokens."""

from __future__ import annotations

from fastapi import Response

from services.api import settings


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    common = {
        "httponly": True,
        "secure": settings.cookie_secure(),
        "samesite": settings.cookie_samesite(),
        "path": "/",
    }
    response.set_cookie(
        key=settings.access_cookie_name(),
        value=access_token,
        max_age=settings.access_token_ttl_seconds(),
        **common,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name(),
        value=refresh_token,
        max_age=settings.refresh_token_ttl_seconds(),
        **common,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.access_cookie_name(),
        path="/",
        secure=settings.cookie_secure(),
        httponly=True,
        samesite=settings.cookie_samesite(),
    )
    response.delete_cookie(
        key=settings.refresh_cookie_name(),
        path="/",
        secure=settings.cookie_secure(),
        httponly=True,
        samesite=settings.cookie_samesite(),
    )
