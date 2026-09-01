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
    """Create a question that is already past review.

    Most tests below are about reviewing answers and comments, or about
    editing, and all of those need a live parent. Tests that care about the
    question's own review lifecycle use _create_pending_question instead.
    """
    defaults: dict[str, Any] = {
        "title": "How do I configure connection pooling?",
        "body": "I need a pool with max size.",
        "supervised": True,
        "tags": ["databases"],
    }
    resp = client.post(
        "/questions", json={**defaults, **overrides}, headers=_agent_headers()
    )
    assert resp.status_code == 201
    return resp.json()["question"]


def _create_pending_question(client: TestClient, **overrides: Any) -> dict[str, Any]:
    question = _create_question(client, supervised=False, **overrides)
    assert question["status"] == "pending"
    return question


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

    def test_answer_item_carries_no_answers_of_its_own(
        self, client: TestClient
    ) -> None:
        """Every item shape is uniform, so non-question items carry []."""
        token = _login(client)
        q = _create_question(client)
        _create_answer(client, q["id"])
        item = client.get("/review/queue", headers=_auth_header(token)).json()["items"][
            0
        ]
        assert item["answers"] == []

    def test_pending_question_arrives_as_one_bundle(self, client: TestClient) -> None:
        """Question and answers are one card, judged with one verdict.

        Approving an answer under a question the reviewer is about to reject
        would strand the knowledge on something nobody can find, so the
        answer must never be offered as a card of its own.
        """
        token = _login(client)
        q = _create_pending_question(client)
        a = _create_answer(client, q["id"])

        body = client.get("/review/queue", headers=_auth_header(token)).json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["type"] == "question"
        assert item["id"] == q["id"]
        assert item["status"] == "pending"
        # content and question are the same row, so the UI can read either.
        assert item["content"]["id"] == q["id"]
        assert item["question"]["id"] == q["id"]
        assert [x["id"] for x in item["answers"]] == [a["id"]]

    def test_question_items_sort_ahead_of_the_rest(self, client: TestClient) -> None:
        token = _login(client)
        live = _create_question(client, title="Why does the build cache miss?")
        _create_answer(client, live["id"])
        pending = _create_pending_question(client, title="Pooling under pgbouncer")

        items = client.get("/review/queue", headers=_auth_header(token)).json()["items"]
        assert [i["type"] for i in items] == ["question", "answer"]
        assert items[0]["id"] == pending["id"]

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

    def test_pending_questions_are_counted_and_rolled_up(
        self, client: TestClient
    ) -> None:
        token = _login(client)
        q = _create_pending_question(client)
        _create_answer(client, q["id"])

        body = client.get("/review/stats", headers=_auth_header(token)).json()
        assert body["pending_questions"] == 1
        # A pending question is not live content, and total_pending is the
        # single number the dashboard badges, so it has to include it.
        assert body["total_questions"] == 0
        assert body["total_pending"] == 2

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


class TestQuestionVerdict:
    """A question is approved and rejected through the same review routes.

    Rejection is the soft-delete: there is no separate delete endpoint, so a
    question that turned out to be repo-specific noise and one that a curator
    retires later travel exactly the same path.
    """

    def test_reject_then_approve(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        resp = client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        resp = client.post(f"/review/{q['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approving_a_question_promotes_its_answers(
        self, client: TestClient
    ) -> None:
        """One verdict clears the whole card."""
        token = _login(client)
        q = _create_pending_question(client)
        a = _create_answer(client, q["id"])

        resp = client.post(f"/review/{q['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 200

        thread = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        ).json()
        assert thread["question"]["status"] == "open"
        assert [t["answer"]["status"] for t in thread["answers"]] == ["approved"]
        assert thread["answers"][0]["answer"]["id"] == a["id"]

        # The bundle is settled, so nothing is left to review.
        queue = client.get("/review/queue", headers=_auth_header(token)).json()
        assert queue["total"] == 0

    def test_rejecting_a_question_drops_the_whole_bundle(
        self, client: TestClient
    ) -> None:
        """The answers stay pending on purpose, which is what makes it undoable."""
        token = _login(client)
        q = _create_pending_question(client)
        a = _create_answer(client, q["id"])

        resp = client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 200

        queue = client.get("/review/queue", headers=_auth_header(token)).json()
        assert queue["total"] == 0

        thread = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        ).json()
        assert thread["question"]["status"] == "deleted"

        # Approving later resurrects the bundle intact, answer included.
        client.post(f"/review/{q['id']}/approve", headers=_auth_header(token))
        thread = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        ).json()
        assert thread["question"]["status"] == "open"
        assert [t["answer"]["id"] for t in thread["answers"]] == [a["id"]]
        assert thread["answers"][0]["answer"]["status"] == "approved"

    def test_reject_twice_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))
        resp = client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))
        assert resp.status_code == 409

    def test_verdict_on_missing_question_returns_404(self, client: TestClient) -> None:
        token = _login(client)
        assert (
            client.post(
                "/review/q_nonexistent/reject", headers=_auth_header(token)
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/review/q_nonexistent/approve", headers=_auth_header(token)
            ).status_code
            == 404
        )

    def test_approve_live_question_returns_409(self, client: TestClient) -> None:
        token = _login(client)
        q = _create_question(client)
        resp = client.post(f"/review/{q['id']}/approve", headers=_auth_header(token))
        assert resp.status_code == 409

    def test_verdict_requires_auth(self, client: TestClient) -> None:
        q = _create_question(client)
        assert client.post(f"/review/{q['id']}/reject").status_code == 401

    def test_rejected_question_hidden_from_agents_but_not_curators(
        self, client: TestClient
    ) -> None:
        """The curation UI must still open a rejected question to restore it."""
        token = _login(client)
        q = _create_question(client, title="pooling with pgbouncer")
        client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))

        agent_results = client.get(
            "/search", params={"q": "pooling pgbouncer"}, headers=_agent_headers()
        ).json()
        assert agent_results == []

        resp = client.get(
            f"/api/questions/{q['id']}/thread", headers=_auth_header(token)
        )
        assert resp.status_code == 200
        assert resp.json()["question"]["status"] == "deleted"

    def test_rejected_question_leaves_the_default_listing(
        self, client: TestClient
    ) -> None:
        token = _login(client)
        q = _create_question(client)
        client.post(f"/review/{q['id']}/reject", headers=_auth_header(token))

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
