"""Tests for human-facing review and editorial routes."""

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


def _create_question(client: TestClient, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "title": "How do I configure connection pooling?",
        "body": "I need a pool with max size.",
        "tags": ["databases"],
    }
    resp = client.post(
        "/questions", json={**defaults, **overrides}, headers=_agent_headers()
    )
    assert resp.status_code == 201
    return resp.json()["question"]


def _create_answer(
    client: TestClient, question_id: str, **overrides: Any
) -> dict[str, Any]:
    defaults = {"body": "Use max_size=10.", "supervised": False}
    resp = client.post(
        f"/questions/{question_id}/answers",
        json={**defaults, **overrides},
        headers=_agent_headers(),
    )
    assert resp.status_code == 201
    return resp.json()


class TestReviewQueue:
    def test_queue_returns_pending(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        _create_answer(client, q["id"])
        resp = client.get("/review/queue", headers=_auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["type"] == "answer"
        assert item["question"]["id"] == q["id"]
        assert item["status"] == "pending"

    def test_queue_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/review/queue")
        assert resp.status_code == 401

    def test_queue_empty_initially(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/review/queue", headers=_auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


class TestApprove:
    def test_approve_pending_answer(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"])
        resp = client.post(f"/review/{a['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_already_reviewed_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"])
        client.post(f"/review/{a['id']}/approve", headers=_auth_header(token))
        resp = client.post(f"/review/{a['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 409

    def test_approve_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        a = _create_answer(client, q["id"])
        resp = client.post(f"/review/{a['id']}/approve")
        assert resp.status_code == 401


class TestReject:
    def test_reject_pending_answer(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"])
        resp = client.post(f"/review/{a['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_reject_already_reviewed_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"])
        client.post(f"/review/{a['id']}/reject", headers=_auth_header(token))
        resp = client.post(f"/review/{a['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 409


class TestReviewStats:
    def test_stats_returns_counts(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.get("/review/stats", headers=_auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert "total_questions" in body
        assert "total_pending" in body
        assert "tags" in body
        assert "recent_activity" in body
        assert "vote_distribution" in body

    def test_stats_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/review/stats")
        assert resp.status_code == 401


class TestEditQuestion:
    def test_edit_question_body(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client, body="original body text")
        resp = client.put(
            f"/questions/{q['id']}",
            json={"body": "updated body text"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "updated body text"

    def test_edit_nonexistent_question(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.put(
            "/questions/q_nonexistent",
            json={"body": "new body"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    def test_edit_question_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        resp = client.put(f"/questions/{q['id']}", json={"body": "new body"})
        assert resp.status_code == 401


class TestEditAnswer:
    def test_edit_answer_body(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], body="original answer")
        resp = client.put(
            f"/answers/{a['id']}",
            json={"body": "updated answer"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "updated answer"

    def test_edit_nonexistent_answer(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.put(
            "/answers/a_nonexistent",
            json={"body": "new body"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404


class TestPinAnswer:
    def test_pin_answer(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], supervised=True)
        resp = client.put(
            f"/questions/{q['id']}/pin",
            json={"answer_id": a["id"]},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["pinned_answer_id"] == a["id"]

    def test_unpin_answer(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], supervised=True)
        client.put(
            f"/questions/{q['id']}/pin",
            json={"answer_id": a["id"]},
            headers=_auth_header(token),
        )
        resp = client.delete(
            f"/questions/{q['id']}/pin",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["pinned_answer_id"] is None

    def test_pin_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        resp = client.put(f"/questions/{q['id']}/pin", json={"answer_id": "a_1"})
        assert resp.status_code == 401


class TestEditHistory:
    def test_question_history(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client, body="original")
        client.put(
            f"/questions/{q['id']}", json={"body": "v2"}, headers=_auth_header(token)
        )
        resp = client.get(f"/questions/{q['id']}/history", headers=_auth_header(token))
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["previous_body"] == "original"

    def test_answer_history(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], body="original answer")
        client.put(
            f"/answers/{a['id']}", json={"body": "v2"}, headers=_auth_header(token)
        )
        resp = client.get(f"/answers/{a['id']}/history", headers=_auth_header(token))
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["previous_body"] == "original answer"

    def test_history_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        resp = client.get(f"/questions/{q['id']}/history")
        assert resp.status_code == 401
