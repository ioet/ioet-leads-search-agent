"""Mock Slack notify service — logs instead of posting webhooks."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI

from mocks.common.logging import RequestResponseLogMiddleware, configure_logging
from mocks.notify.persistence import output_dir, persist_message, persist_messages
from services.common.schemas import NotifyRequest

configure_logging()
logger = logging.getLogger("mocks.notify")
router = APIRouter(prefix="/v1", tags=["notify-mock"])

MESSAGES: list[dict[str, Any]] = []


def _record(msg_type: str, payload: dict[str, Any]) -> None:
    entry = {"type": msg_type, "payload": payload}
    MESSAGES.append(entry)
    persist_messages(MESSAGES)
    path = persist_message(msg_type, payload)
    logger.info("Notify mock wrote %s Slack text to %s", msg_type, path)


@router.get("/messages")
def list_messages() -> dict[str, Any]:
    return {
        "messages": MESSAGES,
        "_output_dir": str(output_dir()),
    }


@router.post("/notify")
def notify(payload: NotifyRequest) -> dict[str, str]:
    body = payload.model_dump()
    _record("notify", body)
    logger.info("Slack notify: %s", body)
    return {"status": "logged"}


@router.post("/failure")
def notify_failure(payload: dict[str, Any]) -> dict[str, str]:
    _record("failure", payload)
    logger.info("Slack failure alert: %s", payload)
    return {"status": "logged"}


app = FastAPI(title="notify-mock", version="0.1.0")
app.add_middleware(RequestResponseLogMiddleware, service_name="notify-mock")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "notify-mock"}


app.include_router(router)
