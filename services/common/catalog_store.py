"""Durable storage for per-campaign ioet skills catalogs."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_DIR = ".cache/skills-catalogs"
DEFAULT_S3_PREFIX = "skills-catalogs"


class CatalogStore(Protocol):
    def save(self, catalog_ref: str, catalog: list[dict[str, Any]]) -> None: ...

    def load(self, catalog_ref: str) -> list[dict[str, Any]] | None: ...


def _safe_ref(catalog_ref: str) -> str:
    ref = catalog_ref.strip()
    if not ref:
        raise ValueError("catalog_ref is required")
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", ref)


def storage_backend() -> str:
    explicit = os.environ.get("SKILLS_CATALOG_STORAGE", "").strip().lower()
    if explicit in {"filesystem", "fs", "local"}:
        return "filesystem"
    if explicit in {"s3"}:
        return "s3"
    if os.environ.get("SKILLS_CATALOG_S3_BUCKET", "").strip():
        return "s3"
    return "filesystem"


def _local_dir() -> Path:
    raw = os.environ.get("SKILLS_CATALOG_LOCAL_DIR", DEFAULT_LOCAL_DIR).strip()
    return Path(raw)


class FilesystemCatalogStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or _local_dir()

    def _path_for(self, catalog_ref: str) -> Path:
        return self.base_dir / f"{_safe_ref(catalog_ref)}.json"

    def save(self, catalog_ref: str, catalog: list[dict[str, Any]]) -> None:
        path = self._path_for(catalog_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        logger.info("Saved skills catalog ref=%s path=%s rows=%d", catalog_ref, path, len(catalog))

    def load(self, catalog_ref: str) -> list[dict[str, Any]] | None:
        path = self._path_for(catalog_ref)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise TypeError(f"Catalog file {path} must contain a JSON list")
        return data


def _is_s3_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
        return code in {"NoSuchKey", "404", "NotFound"}
    return False


class S3CatalogStore:
    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = (bucket or os.environ.get("SKILLS_CATALOG_S3_BUCKET", "")).strip()
        if not self.bucket:
            raise ValueError("SKILLS_CATALOG_S3_BUCKET is not configured")
        self.prefix = (
            prefix if prefix is not None else os.environ.get("SKILLS_CATALOG_S3_PREFIX", DEFAULT_S3_PREFIX)
        ).strip().strip("/")
        self.region = (
            region
            or os.environ.get("SKILLS_CATALOG_S3_REGION", "").strip()
            or os.environ.get("AWS_REGION", "").strip()
            or os.environ.get("AWS_DEFAULT_REGION", "").strip()
            or "us-east-1"
        )

    def _key_for(self, catalog_ref: str) -> str:
        filename = f"{_safe_ref(catalog_ref)}.json"
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def _client(self) -> Any:
        import boto3

        return boto3.client("s3", region_name=self.region)

    def save(self, catalog_ref: str, catalog: list[dict[str, Any]]) -> None:
        key = self._key_for(catalog_ref)
        body = json.dumps(catalog, indent=2).encode("utf-8")
        self._client().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        logger.info(
            "Saved skills catalog ref=%s s3://%s/%s rows=%d",
            catalog_ref,
            self.bucket,
            key,
            len(catalog),
        )

    def load(self, catalog_ref: str) -> list[dict[str, Any]] | None:
        key = self._key_for(catalog_ref)
        client = self._client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_s3_not_found(exc):
                return None
            raise
        body = response["Body"].read().decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, list):
            raise TypeError(f"S3 catalog s3://{self.bucket}/{key} must contain a JSON list")
        return data


class CatalogNotFoundError(FileNotFoundError):
    """Raised when a campaign skills catalog snapshot is missing from durable storage."""


def get_catalog_store() -> CatalogStore:
    if storage_backend() == "s3":
        return S3CatalogStore()
    return FilesystemCatalogStore()


def save_skills_catalog(catalog_ref: str, catalog: list[dict[str, Any]]) -> None:
    get_catalog_store().save(catalog_ref, catalog)


def load_skills_catalog(catalog_ref: str) -> list[dict[str, Any]] | None:
    return get_catalog_store().load(catalog_ref)


def require_skills_catalog(catalog_ref: str) -> list[dict[str, Any]]:
    """Load catalog from durable storage or raise if the campaign snapshot is missing."""
    catalog = load_skills_catalog(catalog_ref)
    if catalog is None:
        raise CatalogNotFoundError(
            f"Skills catalog not found in durable store for ref={catalog_ref!r}. "
            "Run fetch-ioet-skills-catalog in the parent workflow before matching."
        )
    return catalog
