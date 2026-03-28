"""Tests for human-facing Q&A browsing and search routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


def _login(client: TestClient) -> str:
    from team_api.app import _get_store
    from team_api.auth import hash_password

    store = _get_store()
    try:
        store.create_user("reviewer", hash_password("pass123"))
    except Exception:
        pass
    resp = client.post("/auth/login", json={"username": "reviewer", "password": "pass123"})
    return resp.json()["token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_question(client: TestClient, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "title": "How do I configure connection pooling?",
        "body": "I need a pool with max size.",
        "tags": ["databases"],
    }
    resp = client.post("/questions", json={**defaults, **overrides}, headers=_agent_headers())
    assert resp.status_code == 201
    return resp.json()["question"]


def _create_answer(client: TestClient, question_id: str, **overrides: Any) -> dict[str, Any]:
    defaults = {"body": "Use max_size=10.", "supervised": False}
    resp = client.post(
        f"/questions/{question_id}/answers",
        json={**defaults, **overrides},
        headers=_agent_headers(),
    )
    assert resp.status_code == 201
    return resp.json()


# ===================================================================
# List questions
# ===================================================================


class TestListQuestions:
    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/questions")
        assert resp.status_code == 401

    def test_list_empty(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/questions", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_returns_questions(self, client: TestClient) -> None:
        token = _login(client)
        _create_question(client, title="Question 1")
        _create_question(client, title="Question 2")
        resp = client.get("/questions", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_includes_tags(self, client: TestClient) -> None:
        token = _login(client)
        _create_question(client, tags=["python", "django"])
        resp = client.get("/questions", headers=_auth_header(token))
        data = resp.json()
        tag_names = {t["name"] for t in data["items"][0]["tags"]}
        assert tag_names == {"python", "django"}

    def test_filter_by_status(self, client: TestClient) -> None:
        token = _login(client)
        _create_question(client, title="Open Q")
        # All questions start as "open" by default
        resp = client.get("/questions?status=open", headers=_auth_header(token))
        assert resp.json()["total"] == 1
        resp = client.get("/questions?status=resolved", headers=_auth_header(token))
        assert resp.json()["total"] == 0

    def test_filter_by_tag(self, client: TestClient) -> None:
        token = _login(client)
        _create_question(client, title="Python Q", tags=["python"])
        _create_question(client, title="Go Q", tags=["go"])
        resp = client.get("/questions?tag=python", headers=_auth_header(token))
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["question"]["title"] == "Python Q"

    def test_pagination(self, client: TestClient) -> None:
        token = _login(client)
        for i in range(5):
            _create_question(client, title=f"Q{i}", tags=[f"tag{i}"])
        resp = client.get("/questions?limit=2&offset=0", headers=_auth_header(token))
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        resp2 = client.get("/questions?limit=2&offset=2", headers=_auth_header(token))
        data2 = resp2.json()
        assert data2["total"] == 5
        assert len(data2["items"]) == 2
        ids1 = {i["question"]["id"] for i in data["items"]}
        ids2 = {i["question"]["id"] for i in data2["items"]}
        assert ids1.isdisjoint(ids2)


# ===================================================================
# Search
# ===================================================================


class TestSearchQuestions:
    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/questions/search?q=pool")
        assert resp.status_code == 401

    def test_missing_query_returns_400(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/questions/search", headers=_auth_header(token))
        assert resp.status_code == 400
        assert "Search query required" in resp.json()["detail"]

    def test_search_returns_results(self, client: TestClient) -> None:
        token = _login(client)
        _create_question(client, title="Connection pooling", body="How to configure pool size")
        resp = client.get("/questions/search?q=pooling", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) > 0

    def test_search_no_results(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/questions/search?q=nonexistent_xyz", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 0


# ===================================================================
# Question thread
# ===================================================================


class TestQuestionThread:
    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/questions/fake-id/thread")
        assert resp.status_code == 401

    def test_not_found(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/questions/nonexistent/thread", headers=_auth_header(token))
        assert resp.status_code == 404

    def test_returns_thread(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client, tags=["databases"])
        _create_answer(client, q["id"], supervised=True)
        resp = client.get(f"/questions/{q['id']}/thread", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["question"]["id"] == q["id"]
        assert len(data["answers"]) == 1
        assert "tags" in data

    def test_thread_includes_pending_answers(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        _create_answer(client, q["id"], supervised=False)  # pending
        _create_answer(client, q["id"], supervised=True)  # approved
        resp = client.get(f"/questions/{q['id']}/thread", headers=_auth_header(token))
        data = resp.json()
        assert len(data["answers"]) == 2
        statuses = [a["answer"]["status"] for a in data["answers"]]
        # Approved comes first, then pending
        assert statuses[0] == "approved"
        assert statuses[1] == "pending"
