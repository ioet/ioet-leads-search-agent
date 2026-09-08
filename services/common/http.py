"""Shared FastAPI helpers for microservices."""

from fastapi import APIRouter, FastAPI


def create_app(service_name: str) -> FastAPI:
    app = FastAPI(title=service_name, version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    return app


def stub_router(prefix: str, service_name: str) -> APIRouter:
    """Placeholder router returned until integration endpoints are implemented."""
    router = APIRouter(prefix=prefix)

    @router.get("/")
    def root() -> dict[str, str]:
        return {"service": service_name, "status": "stub"}

    return router
