"""Tests for authentication: JWT, API key, and auth endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient
from team_api.app import app
from team_api.auth import create_token, hash_password, verify_password, verify_token


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ACQ_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ACQ_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ACQ_API_KEYS", json.dumps({"valid-key": "agent-smith"}))
    with TestClient(app) as c:
        yield c


def _seed_user(
    client: TestClient, username: str = "peter", password: str = "secret123"
) -> None:
    from team_api.app import _get_store

    store = _get_store()
    store.create_user(username, hash_password(password))


class TestPasswordHashing:
    def test_verify_correct_password(self) -> None:
        hashed = hash_password("secret123")
        assert verify_password("secret123", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("secret123")
        assert verify_password("wrong", hashed) is False


class TestJWT:
    def test_create_and_verify_token(self) -> None:
        test_secret = "test-secret"  # pragma: allowlist secret
        token = create_token("peter", secret=test_secret, ttl_hours=24)
        payload = verify_token(token, secret=test_secret)
        assert payload["sub"] == "peter"

    def test_expired_token_rejected(self) -> None:
        test_secret = "test-secret"  # pragma: allowlist secret
        token = create_token("peter", secret=test_secret, ttl_hours=0)
        time.sleep(1)
        with pytest.raises(jwt.ExpiredSignatureError):
            verify_token(token, secret=test_secret)

    def test_invalid_token_rejected(self) -> None:
        test_secret = "test-secret"  # pragma: allowlist secret
        with pytest.raises(jwt.DecodeError):
            verify_token("not.a.token", secret=test_secret)

    def test_wrong_secret_rejected(self) -> None:
        secret_a = "secret-a"  # pragma: allowlist secret
        secret_b = "secret-b"  # pragma: allowlist secret
        token = create_token("peter", secret=secret_a)
        with pytest.raises(jwt.InvalidSignatureError):
            verify_token(token, secret=secret_b)


class TestApiKeyAuth:
    def test_valid_api_key_accepted(self, client: TestClient) -> None:
        # The /status endpoint uses agent identity (API key auth).
        resp = client.get("/status", headers={"X-API-Key": "valid-key"})
        assert resp.status_code == 200

    def test_invalid_api_key_returns_401(self, client: TestClient) -> None:
        resp = client.get("/status", headers={"X-API-Key": "bad-key"})
        assert resp.status_code == 401

    def test_missing_api_key_returns_401(self, client: TestClient) -> None:
        resp = client.get("/status")
        assert resp.status_code == 401


class TestLoginEndpoint:
    test_password = "secret123"  # pragma: allowlist secret

    def test_login_success(self, client: TestClient) -> None:
        _seed_user(client)
        resp = client.post(
            "/auth/login", json={"username": "peter", "password": self.test_password}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["username"] == "peter"

    def test_login_wrong_password(self, client: TestClient) -> None:
        _seed_user(client)
        resp = client.post(
            "/auth/login",
            json={"username": "peter", "password": "wrong"},  # pragma: allowlist secret
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/login", json={"username": "nobody", "password": self.test_password}
        )
        assert resp.status_code == 401


class TestAuthMe:
    test_password = "secret123"  # pragma: allowlist secret

    def test_me_with_valid_token(self, client: TestClient) -> None:
        _seed_user(client)
        login = client.post(
            "/auth/login", json={"username": "peter", "password": self.test_password}
        )
        token = login.json()["token"]
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "peter"

    def test_me_without_token(self, client: TestClient) -> None:
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client: TestClient) -> None:
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401


def test_agent_key_from_database(client, monkeypatch):
    """Agent key stored in DB should authenticate without ACQ_API_KEYS env var."""
    monkeypatch.delenv("ACQ_API_KEYS", raising=False)
    from team_api.app import _get_store

    store = _get_store()
    store.create_agent_key("acq_dbkey123", "dbuser-agent", "dbuser")

    resp = client.get("/status", headers={"X-API-Key": "acq_dbkey123"})
    assert resp.status_code == 200


def test_db_key_takes_precedence_over_env(client, monkeypatch):
    """DB key should be checked before env var."""
    monkeypatch.setenv("ACQ_API_KEYS", json.dumps({"acq_dbkey123": "env-agent"}))
    from team_api.app import _get_store

    store = _get_store()
    store.create_agent_key("acq_dbkey123", "db-agent", "dbuser")

    resp = client.get("/status", headers={"X-API-Key": "acq_dbkey123"})
    assert resp.status_code == 200


def test_create_agent_key_success(client, monkeypatch):
    """POST /auth/agent-key with valid GitHub token creates a key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"login": "testuser", "name": "Test User"}

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_name"] == "testuser-agent"
    assert data["github_username"] == "testuser"
    assert data["api_key"].startswith("acq_")


def test_create_agent_key_returns_existing(client, monkeypatch):
    """If user already has a key, return the existing one."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"login": "testuser", "name": "Test User"}

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp1 = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )
        resp2 = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )

    assert resp1.json()["api_key"] == resp2.json()["api_key"]


def test_create_agent_key_invalid_github_token(client):
    """POST /auth/agent-key with invalid GitHub token returns 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_bad_token"},
        )

    assert resp.status_code == 401
