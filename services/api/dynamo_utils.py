"""Helpers for DynamoDB attribute types."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def from_dynamo(value: Any) -> Any:
    """Convert DynamoDB Decimals (and nested structures) to plain Python types."""
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    return value
