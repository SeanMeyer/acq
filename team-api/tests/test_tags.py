"""Tests for tag management routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from team_api.app import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ACQ_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ACQ_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ACQ_API_KEYS", json.dumps({"agent-key": "agent-smith"}))
    with TestClient(app) as c:
        yield c


def _agent_headers() -> dict[str, str]:
    return {"X-API-Key": "agent-key"}


def _login(
    client: TestClient, username: str = "reviewer", password: str = "pass123"
) -> str:
    from team_api.app import _get_store
    from team_api.auth import hash_password

    store = _get_store()
    try:
        store.create_user(username, hash_password(password))
    except Exception:
        pass
    resp = client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_tags(client: TestClient, names: list[str]) -> list[str]:
    """Create tags by creating a question with those tags; returns tag ids."""
    resp = client.post(
        "/questions",
        json={
            "title": f"question with tags {' '.join(names)}",
            "body": "body",
            "created_by": "agent-smith",
            "tags": names,
        },
        headers=_agent_headers(),
    )
    assert resp.status_code == 201
    # Fetch tag ids via listing.
    tags_resp = client.get("/tags", headers=_agent_headers())
    tag_map = {t["name"]: t["id"] for t in tags_resp.json()}
    return [tag_map[n] for n in names]


class TestMergeTags:
    def test_merge_tags_success(self, client: TestClient) -> None:
        token = _login(client)
        source_id, target_id = _create_tags(client, ["py", "python"])
        resp = client.post(
            "/tags/merge",
            json={"source_id": source_id, "target_id": target_id},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is True
        assert body["target"]["name"] == "python"

    def test_merge_deletes_source_tag(self, client: TestClient) -> None:
        token = _login(client)
        source_id, target_id = _create_tags(client, ["js", "javascript"])
        client.post(
            "/tags/merge",
            json={"source_id": source_id, "target_id": target_id},
            headers=_auth_header(token),
        )
        tags_resp = client.get("/tags", headers=_agent_headers())
        names = [t["name"] for t in tags_resp.json()]
        assert "js" not in names
        assert "javascript" in names

    def test_merge_missing_source_returns_404(self, client: TestClient) -> None:
        token = _login(client)
        (target_id,) = _create_tags(client, ["python"])
        resp = client.post(
            "/tags/merge",
            json={"source_id": "t_nonexistent", "target_id": target_id},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    def test_merge_missing_target_returns_404(self, client: TestClient) -> None:
        token = _login(client)
        (source_id,) = _create_tags(client, ["py"])
        resp = client.post(
            "/tags/merge",
            json={"source_id": source_id, "target_id": "t_nonexistent"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    def test_merge_requires_auth(self, client: TestClient) -> None:
        resp = client.post(
            "/tags/merge",
            json={"source_id": "t_1", "target_id": "t_2"},
        )
        assert resp.status_code == 401
