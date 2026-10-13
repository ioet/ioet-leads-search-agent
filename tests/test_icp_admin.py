"""ICP admin extract / validate / publish API and S3 cache TTL."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.common.icp import IdealCustomerProfile, clear_icp_s3_cache, load_icp
from services.icp.app import app
from services.icp.extract import extract_icp_from_text

ROOT = Path(__file__).resolve().parents[1]
ICP_PATH = ROOT / "data" / "icp.json"


def _canonical() -> dict:
    return json.loads(ICP_PATH.read_text(encoding="utf-8"))


def test_extract_icp_from_text_validates(monkeypatch) -> None:
    canonical = _canonical()
    bedrock = MagicMock()
    bedrock.converse_json.return_value = canonical
    icp, errors = extract_icp_from_text(
        "Primary segment: AI/ML companies 10-500 US/CA",
        source_filename="ioet_Current_ICP.pdf",
        current_icp=canonical,
        bedrock=bedrock,
    )
    assert errors == []
    IdealCustomerProfile.model_validate(icp)
    assert icp["source"] == "ioet_Current_ICP.pdf"
    system_arg, user_arg = bedrock.converse_json.call_args[0]
    assert "ONLY valid JSON" in system_arg
    assert "ioet_Current_ICP.pdf" in user_arg


def test_extract_icp_from_text_returns_partial_on_invalid() -> None:
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {"version": "x", "source": "a.pdf"}
    candidate, errors = extract_icp_from_text(
        "incomplete",
        source_filename="a.pdf",
        bedrock=bedrock,
    )
    assert candidate["version"] == "x"
    assert errors
    assert any(err.get("loc") for err in errors)


def test_extract_endpoint_returns_draft(monkeypatch) -> None:
    canonical = _canonical()
    monkeypatch.setattr("services.icp.handler.pdf_to_text", lambda _b: "ICP body")
    monkeypatch.setattr(
        "services.icp.handler.extract_icp_from_text",
        lambda *_a, **_k: (canonical, []),
    )
    monkeypatch.setattr(
        "services.icp.handler.get_current_icp",
        lambda: (canonical, None, None),
    )
    monkeypatch.setattr(
        "services.icp.handler.save_upload",
        lambda _b, _n: "11111111-1111-1111-1111-111111111111",
    )

    client = TestClient(app)
    response = client.post(
        "/v1/icp/extract",
        files={"file": ("ioet.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["upload_id"] == "11111111-1111-1111-1111-111111111111"
    IdealCustomerProfile.model_validate(body["icp"])


def test_extract_rejects_non_pdf() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/icp/extract",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_validate_and_put(monkeypatch) -> None:
    canonical = _canonical()
    client = TestClient(app)

    ok = client.post("/v1/icp/validate", json={"icp": canonical})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    bad = client.post("/v1/icp/validate", json={"icp": {"version": "x"}})
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert bad.json()["errors"]

    rejected = client.put("/v1/icp", json={"icp": {"version": "x"}})
    assert rejected.status_code == 422

    written: dict = {}

    def fake_put(icp, *, upload_id, source_filename):
        written["icp"] = icp
        written["upload_id"] = upload_id
        written["source_filename"] = source_filename
        return "ver-1"

    monkeypatch.setattr("services.icp.handler.put_icp", fake_put)
    published = client.put(
        "/v1/icp",
        json={"icp": canonical, "upload_id": None, "source_filename": "ioet.pdf"},
    )
    assert published.status_code == 200
    assert published.json()["s3_version_id"] == "ver-1"
    assert written["icp"]["version"] == canonical["version"]
    assert "put_object" not in written  # invalid path never reached S3 helper


def test_get_icp_local() -> None:
    client = TestClient(app)
    response = client.get("/v1/icp")
    assert response.status_code == 200
    IdealCustomerProfile.model_validate(response.json()["icp"])


def test_s3_icp_cache_ttl(monkeypatch) -> None:
    payload = ICP_PATH.read_bytes()
    monkeypatch.setenv("ICP_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("ICP_S3_KEY", "icp/icp.json")
    monkeypatch.setenv("ICP_S3_CACHE_TTL_SECONDS", "60")
    clear_icp_s3_cache()

    client = MagicMock()
    body = MagicMock()
    body.read.return_value = payload
    client.get_object.return_value = {"Body": body}

    monotonic = iter([100.0, 100.5, 200.0])
    monkeypatch.setattr("services.common.icp.time.monotonic", lambda: next(monotonic))

    monkeypatch.setattr("services.common.icp._s3_client", lambda: client)

    first = load_icp()
    second = load_icp()
    assert first.version == second.version
    assert client.get_object.call_count == 1
    third = load_icp()
    assert third.version == first.version
    assert client.get_object.call_count == 2
