"""Campaign API FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.db import ensure_tables
from services.api.routers import auth as auth_router
from services.api.routers import campaigns as campaigns_router
from services.api.routers import icps as icps_router
from services.api.routers import internal as internal_router
from services.api.routers import users as users_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("API_ENSURE_TABLES", "").lower() in {"1", "true", "yes"}:
        logger.info("Ensuring DynamoDB tables exist")
        ensure_tables()
    yield


def create_api_app() -> FastAPI:
    app = FastAPI(
        title="leads-campaign-api",
        version="0.1.0",
        lifespan=lifespan,
    )

    origins = [
        o.strip()
        for o in os.environ.get(
            "API_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "leads-campaign-api"}

    app.include_router(auth_router.router, prefix="/api")
    app.include_router(users_router.router, prefix="/api")
    app.include_router(icps_router.router, prefix="/api")
    app.include_router(campaigns_router.router, prefix="/api")
    app.include_router(internal_router.router, prefix="/api")
    return app


app = create_api_app()
