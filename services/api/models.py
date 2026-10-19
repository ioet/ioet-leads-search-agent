"""Shared domain enums and Pydantic models for the campaign API."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    email: str
    name: str | None = None
    password_hash: str
    role: UserRole
    status: UserStatus
    created_at: str
    updated_at: str
    email_verified_at: str | None = None


class UserPublic(BaseModel):
    user_id: str
    email: str
    role: UserRole
    status: UserStatus
    created_at: str
    email_verified_at: str | None = None


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UpdateUserRequest(BaseModel):
    role: UserRole | None = None
    status: UserStatus | None = None


class MessageResponse(BaseModel):
    ok: bool = True
    message: str


class ErrorBody(BaseModel):
    detail: str | list[Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
