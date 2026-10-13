"""Durable skills catalog store tests."""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.common.catalog_store import (
    FilesystemCatalogStore,
    S3CatalogStore,
    load_skills_catalog,
    save_skills_catalog,
    storage_backend,
)


def test_storage_backend_defaults_to_filesystem(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    monkeypatch.delenv("SKILLS_CATALOG_STORAGE", raising=False)
    assert storage_backend() == "filesystem"


def test_storage_backend_uses_s3_when_bucket_set(monkeypatch) -> None:
    monkeypatch.setenv("SKILLS_CATALOG_S3_BUCKET", "leads-agent-catalogs")
    assert storage_backend() == "s3"


def test_filesystem_store_roundtrip(tmp_path) -> None:
    store = FilesystemCatalogStore(base_dir=tmp_path)
    catalog = [{"employee_id": "1", "display_name": "Ada", "skills": ["Python"]}]
    store.save("parent-wf-123", catalog)
    loaded = store.load("parent-wf-123")
    assert loaded == catalog
    path = tmp_path / "parent-wf-123.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == catalog


def test_filesystem_store_missing_returns_none(tmp_path) -> None:
    store = FilesystemCatalogStore(base_dir=tmp_path)
    assert store.load("missing-ref") is None


def test_s3_store_save_and_load() -> None:
    bucket = "leads-agent-catalogs"
    store = S3CatalogStore(bucket=bucket, prefix="skills-catalogs", region="us-east-1")
    catalog = [{"employee_id": "1", "display_name": "Ada", "skills": ["Python"]}]
    client = MagicMock()
    client.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps(catalog).encode("utf-8"))
    }

    with patch.object(store, "_client", return_value=client):
        store.save("parent-wf-456", catalog)
        loaded = store.load("parent-wf-456")

    client.put_object.assert_called_once()
    put_kwargs = client.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == bucket
    assert put_kwargs["Key"] == "skills-catalogs/parent-wf-456.json"
    assert put_kwargs["ContentType"] == "application/json"
    assert loaded == catalog


def test_s3_store_missing_key_returns_none() -> None:
    store = S3CatalogStore(bucket="leads-agent-catalogs", prefix="skills-catalogs")
    client = MagicMock()
    err = Exception("not found")
    err.response = {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}  # type: ignore[attr-defined]
    client.get_object.side_effect = err

    with patch.object(store, "_client", return_value=client):
        assert store.load("missing-ref") is None


def test_save_and_load_via_helpers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SKILLS_CATALOG_LOCAL_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    catalog = [{"employee_id": "9", "display_name": "Grace", "skills": ["AWS"]}]
    save_skills_catalog("campaign-abc", catalog)
    assert load_skills_catalog("campaign-abc") == catalog


def test_require_skills_catalog_raises_when_missing(tmp_path, monkeypatch) -> None:
    from services.common.catalog_store import CatalogNotFoundError, require_skills_catalog

    monkeypatch.setenv("SKILLS_CATALOG_LOCAL_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    with pytest.raises(CatalogNotFoundError, match="missing-ref"):
        require_skills_catalog("missing-ref")


def test_require_skills_catalog_falls_back_to_latest(tmp_path, monkeypatch) -> None:
    from services.common.catalog_store import require_skills_catalog

    monkeypatch.setenv("SKILLS_CATALOG_LOCAL_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    latest = [{"employee_id": "3", "display_name": "Ada", "skills": ["Python"]}]
    save_skills_catalog("latest", latest)

    assert require_skills_catalog("missing-ref") == latest
    # Parent fetch step failed: LittleHorse passes a NULL catalog-ref.
    assert require_skills_catalog(None) == latest
    assert require_skills_catalog("") == latest
