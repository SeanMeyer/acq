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


def _create_comment(
    client: TestClient,
    parent_id: str,
    parent_type: str = "question",
    body: str = "A note.",
) -> dict[str, Any]:
    resp = client.post(
        "/comments",
        json={"parent_id": parent_id, "parent_type": parent_type, "body": body},
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

    def test_edit_question_title_and_tags(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client, title="Old title", tags=["databases"])
        resp = client.put(
            f"/questions/{q['id']}",
            json={"title": "New title", "tags": ["pooling", "postgres"]},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New title"
        thread = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        ).json()
        assert sorted(t["name"] for t in thread["tags"]) == ["pooling", "postgres"]

    def test_omitted_fields_are_left_alone(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client, title="Keep me", body="original body text")
        resp = client.put(
            f"/questions/{q['id']}",
            json={"body": "updated body text"},
            headers=_auth_header(token),
        )
        assert resp.json()["title"] == "Keep me"

    def test_edit_agent_authored_question(self, client: TestClient) -> None:
        """Authorship must not gate editing: any logged-in human may edit."""
        token = _login(client)
        q = _create_question(client)  # created via the agent key
        assert q["created_by_type"] == "agent"
        resp = client.put(
            f"/questions/{q['id']}",
            json={"body": "a human fixed this up"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "a human fixed this up"


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


class TestEditComment:
    def test_edit_comment_body(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        c = _create_comment(client, q["id"], body="original comment")
        resp = client.put(
            f"/comments/{c['id']}",
            json={"body": "updated comment"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "updated comment"

    def test_edit_nonexistent_comment(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.put(
            "/comments/c_nonexistent",
            json={"body": "new body"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    def test_edit_comment_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        c = _create_comment(client, q["id"])
        resp = client.put(f"/comments/{c['id']}", json={"body": "new body"})
        assert resp.status_code == 401

    def test_comment_history(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        c = _create_comment(client, q["id"], body="original comment")
        client.put(
            f"/comments/{c['id']}",
            json={"body": "updated comment"},
            headers=_auth_header(token),
        )
        resp = client.get(f"/comments/{c['id']}/history", headers=_auth_header(token))
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["previous_body"] == "original comment"
        assert history[0]["edited_by_type"] == "human"


class TestDeleteQuestion:
    def test_delete_then_restore(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        resp = client.delete(f"/questions/{q['id']}", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        resp = client.post(f"/questions/{q['id']}/restore", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"

    def test_delete_twice_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        client.delete(f"/questions/{q['id']}", headers=_auth_header(token))
        resp = client.delete(f"/questions/{q['id']}", headers=_auth_header(token))
        assert resp.status_code == 409

    def test_delete_missing_returns_404(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.delete("/questions/q_nonexistent", headers=_auth_header(token))
        assert resp.status_code == 404

    def test_restore_undeleted_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        resp = client.post(f"/questions/{q['id']}/restore", headers=_auth_header(token))
        assert resp.status_code == 409

    def test_delete_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        assert client.delete(f"/questions/{q['id']}").status_code == 401

    def test_deleted_question_hidden_from_agents_but_not_curators(
        self, client: TestClient
    ) -> None:
        """The curation UI must still open a deleted question to restore it."""
        token = _login(client)
        q = _create_question(client, title="pooling with pgbouncer")
        client.delete(f"/questions/{q['id']}", headers=_auth_header(token))

        agent_results = client.get(
            "/search", params={"q": "pooling pgbouncer"}, headers=_agent_headers()
        ).json()
        assert agent_results == []

        resp = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        )
        assert resp.status_code == 200
        assert resp.json()["question"]["status"] == "deleted"

    def test_deleted_question_leaves_the_default_listing(
        self, client: TestClient
    ) -> None:
        token = _login(client)
        q = _create_question(client)
        client.delete(f"/questions/{q['id']}", headers=_auth_header(token))

        listing = client.get("/api/questions", headers=_auth_header(token)).json()
        assert listing["total"] == 0
        listing = client.get(
            "/api/questions", params={"status": "deleted"}, headers=_auth_header(token)
        ).json()
        assert [i["question"]["id"] for i in listing["items"]] == [q["id"]]


class TestDeleteAnswerAndComment:
    """Rejection doubles as soft-delete, so it must work on live content."""

    def test_reject_approved_answer_then_restore(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], supervised=True)  # auto-approved

        resp = client.post(f"/review/{a['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        resp = client.post(f"/review/{a['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_question_level_comment(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        c = _create_comment(client, q["id"], parent_type="question")
        client.post(f"/review/{c['id']}/approve", headers=_auth_header(token))
        resp = client.post(f"/review/{c['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 200

    def test_reject_missing_content_returns_404(self, client: TestClient) -> None:
        token = _login(client)
        resp = client.post("/review/a_nonexistent/reject", headers=_auth_header(token))
        assert resp.status_code == 404

    def test_rejected_content_reachable_for_restore_in_thread(
        self, client: TestClient
    ) -> None:
        token = _login(client)
        q = _create_question(client)
        a = _create_answer(client, q["id"], supervised=True)
        c = _create_comment(client, q["id"], parent_type="question")
        client.post(f"/review/{c['id']}/approve", headers=_auth_header(token))
        client.post(f"/review/{a['id']}/reject", headers=_auth_header(token))
        client.post(f"/review/{c['id']}/reject", headers=_auth_header(token))

        thread = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        ).json()
        assert [t["answer"]["id"] for t in thread["answers"]] == [a["id"]]
        assert thread["answers"][0]["answer"]["status"] == "rejected"
        assert [x["id"] for x in thread["comments"]] == [c["id"]]
        assert thread["comments"][0]["status"] == "rejected"


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
