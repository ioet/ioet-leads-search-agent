from __future__ import annotations

from typing import Any

import requests
from fastapi import APIRouter, HTTPException

from services.common.schemas import NotifyRequest
from services.notify.client import SlackClient, SlackConfigError

router = APIRouter(prefix="/v1", tags=["notify"])


def _client() -> SlackClient:
    return SlackClient()


@router.post("/notify")
def notify(payload: NotifyRequest) -> dict[str, str]:
    """Post a message to Slack. Caller owns message formatting."""
    try:
        return _client().notify(payload)
    except SlackConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Slack webhook failed") from exc


@router.post("/failure")
def notify_failure(payload: dict[str, Any]) -> dict[str, str]:
    """Post failure alert to Slack."""
    try:
        return _client().failure(payload)
    except SlackConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Slack webhook failed") from exc
