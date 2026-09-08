"""Campaign size limits from environment (companies + contacts per company)."""

from __future__ import annotations

import os


def env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return value


def max_companies(default: int = 25) -> int:
    """Max companies to search / keep (``MAX_COMPANIES``)."""
    return env_positive_int("MAX_COMPANIES", default)


def max_contacts_per_company(default: int = 10) -> int:
    """Max decision-maker contacts per company (``MAX_CONTACTS_PER_COMPANY``)."""
    return env_positive_int("MAX_CONTACTS_PER_COMPANY", default)
