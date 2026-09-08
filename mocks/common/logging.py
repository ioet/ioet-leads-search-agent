"""Log inbound/outbound HTTP for mock services."""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("mocks.http")


def _preview(body: bytes, limit: int = 1200) -> str:
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + "…"
    return text


class RequestResponseLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, service_name: str) -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next) -> Response:
        body = await request.body()
        logger.info(
            "[%s] --> %s %s body=%s",
            self.service_name,
            request.method,
            request.url.path,
            _preview(body),
        )
        response = await call_next(request)
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        payload = b"".join(chunks)
        logger.info(
            "[%s] <-- %s %s status=%s body=%s",
            self.service_name,
            request.method,
            request.url.path,
            response.status_code,
            _preview(payload),
        )
        return Response(
            content=payload,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
