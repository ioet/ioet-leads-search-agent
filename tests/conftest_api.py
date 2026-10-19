"""Shared helpers for campaign API tests.

Imported by test_api_*.py modules (not auto-loaded as pytest conftest to avoid
affecting unrelated suites' env).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1]


def configure_api_test_env() -> None:
    os.environ["API_JWT_SECRET"] = "test-jwt-secret-not-for-prod-32b!"
    os.environ["API_ALLOWED_EMAIL_DOMAIN"] = "ioet.com"
    os.environ["API_EMAIL_MODE"] = "log"
    os.environ["API_ENSURE_TABLES"] = "false"
    os.environ["API_COOKIE_SECURE"] = "false"
    os.environ["API_USERS_TABLE"] = "test-leads-api-users"
    os.environ["API_REFRESH_TOKENS_TABLE"] = "test-leads-api-refresh-tokens"
    os.environ["API_ICPS_TABLE"] = "test-leads-api-icps"
    os.environ["API_CAMPAIGNS_TABLE"] = "test-leads-api-campaigns"
    os.environ["API_SCHEDULES_TABLE"] = "test-leads-api-schedules"
    os.environ["API_CAMPAIGN_RUNS_TABLE"] = "test-leads-api-campaign-runs"
    os.environ.pop("DYNAMODB_ENDPOINT_URL", None)
    os.environ.pop("API_ICP_FILES_BUCKET", None)
    os.environ.pop("ICP_S3_BUCKET", None)


def make_api_client() -> Iterator[TestClient]:
    configure_api_test_env()
    with mock_aws():
        from services.api.db import ensure_tables, reset_dynamodb_cache

        reset_dynamodb_cache()
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
        boto3.setup_default_session(region_name="us-east-1")
        ensure_tables()

        from services.api.app import create_api_app

        app = create_api_app()
        with TestClient(app) as client:
            yield client
        reset_dynamodb_cache()


def sample_icp_dict() -> dict:
    return json.loads((ROOT / "data" / "icp.json").read_text(encoding="utf-8"))


def signup_verify_login(
    client: TestClient,
    *,
    email: str = "dev@ioet.com",
    password: str = "password123",
    capsys: pytest.CaptureFixture[str] | None = None,
) -> dict:
    resp = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    if capsys is None:
        raise RuntimeError("capsys required to capture verification token")
    out = capsys.readouterr().out
    token = out.split("verify-email?token=")[1].split()[0].strip()
    assert client.post(f"/api/auth/verify?token={token}").status_code == 200
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()
