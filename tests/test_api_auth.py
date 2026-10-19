"""Campaign API auth tests (DynamoDB via moto)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest_api import make_api_client


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    yield from make_api_client()


def _signup(client: TestClient, email: str = "dev@ioet.com", password: str = "password123") -> None:
    resp = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text


def test_health(api_client: TestClient) -> None:
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "leads-campaign-api"


def test_signup_rejects_non_ioet_domain(api_client: TestClient) -> None:
    resp = api_client.post(
        "/api/auth/signup",
        json={"email": "person@gmail.com", "password": "password123"},
    )
    assert resp.status_code == 400
    assert "ioet.com" in resp.json()["detail"]


def test_signup_login_requires_verification(api_client: TestClient) -> None:
    _signup(api_client)
    resp = api_client.post(
        "/api/auth/login",
        json={"email": "dev@ioet.com", "password": "password123"},
    )
    assert resp.status_code == 403


def test_signup_verify_login_me_logout(api_client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    resp = api_client.post(
        "/api/auth/signup",
        json={"email": "dev@ioet.com", "password": "password123"},
    )
    assert resp.status_code == 201
    captured = capsys.readouterr()
    assert "verify-email?token=" in captured.out
    token = captured.out.split("verify-email?token=")[1].split()[0].strip()

    verify = api_client.post(f"/api/auth/verify?token={token}")
    assert verify.status_code == 200

    login = api_client.post(
        "/api/auth/login",
        json={"email": "dev@ioet.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["email"] == "dev@ioet.com"
    assert login.json()["role"] == "member"
    assert "access_token" in login.cookies
    assert "refresh_token" in login.cookies

    me = api_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == login.json()["user_id"]

    logout = api_client.post("/api/auth/logout")
    assert logout.status_code == 200
    me_after = api_client.get("/api/auth/me")
    assert me_after.status_code == 401


def test_refresh_rotates_cookie(api_client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    api_client.post("/api/auth/signup", json={"email": "dev@ioet.com", "password": "password123"})
    token = capsys.readouterr().out.split("verify-email?token=")[1].split()[0].strip()
    api_client.post(f"/api/auth/verify?token={token}")
    api_client.post("/api/auth/login", json={"email": "dev@ioet.com", "password": "password123"})
    old_refresh = api_client.cookies.get("refresh_token")
    assert old_refresh

    refreshed = api_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    new_refresh = api_client.cookies.get("refresh_token")
    assert new_refresh
    assert new_refresh != old_refresh


def test_duplicate_signup(api_client: TestClient) -> None:
    _signup(api_client)
    again = api_client.post(
        "/api/auth/signup",
        json={"email": "dev@ioet.com", "password": "password123"},
    )
    assert again.status_code == 409


def test_admin_user_list_requires_admin(api_client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    api_client.post("/api/auth/signup", json={"email": "dev@ioet.com", "password": "password123"})
    token = capsys.readouterr().out.split("verify-email?token=")[1].split()[0].strip()
    api_client.post(f"/api/auth/verify?token={token}")
    api_client.post("/api/auth/login", json={"email": "dev@ioet.com", "password": "password123"})

    denied = api_client.get("/api/users")
    assert denied.status_code == 403

    from services.api.models import UserRole
    from services.api.stores import users as user_store

    user = user_store.get_user_by_email("dev@ioet.com")
    assert user
    user_store.update_user(user.user_id, role=UserRole.ADMIN)

    # Re-login so JWT carries admin role
    api_client.post("/api/auth/login", json={"email": "dev@ioet.com", "password": "password123"})
    listed = api_client.get("/api/users")
    assert listed.status_code == 200
    assert any(u["email"] == "dev@ioet.com" for u in listed.json())
