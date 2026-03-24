"""Tests for agent-facing ACQ team API routes."""

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


def _create_question(client: TestClient, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "title": "How do I configure connection pooling?",
        "body": "I need to set up a pool with a max size.",
        "created_by": "agent-smith",
        "tags": ["databases"],
    }
    resp = client.post("/questions", json={**defaults, **overrides}, headers=_agent_headers())
    assert resp.status_code == 201
    return resp.json()


def _create_and_approve_answer(client: TestClient, question_id: str, body: str = "Use max_size=10") -> dict[str, Any]:
    resp = client.post(
        f"/questions/{question_id}/answers",
        json={"body": body, "supervised": True},
        headers=_agent_headers(),
    )
    assert resp.status_code == 201
    return resp.json()


class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_no_auth_required(self, client: TestClient) -> None:
        # Health is always unauthenticated.
        resp = client.get("/health")
        assert resp.status_code == 200


class TestStatus:
    def test_status_requires_api_key(self, client: TestClient) -> None:
        resp = client.get("/status")
        assert resp.status_code == 401

    def test_status_returns_counts(self, client: TestClient) -> None:
        resp = client.get("/status", headers=_agent_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "total_questions" in body
        assert "total_answers" in body
        assert "pending" in body

    def test_status_invalid_key_returns_401(self, client: TestClient) -> None:
        resp = client.get("/status", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401


class TestSearch:
    def test_search_requires_api_key(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "connection pool"})
        assert resp.status_code == 401

    def test_search_returns_results(self, client: TestClient) -> None:
        r = _create_question(client, title="connection pool max size configuration")
        question_id = r["question"]["id"]
        _create_and_approve_answer(client, question_id)
        resp = client.get("/search", params={"q": "connection pool"}, headers=_agent_headers())
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1

    def test_search_result_has_max_3_answers(self, client: TestClient) -> None:
        r = _create_question(client, title="max answers search test scenario")
        question_id = r["question"]["id"]
        for i in range(5):
            _create_and_approve_answer(client, question_id, body=f"Answer {i} with more content here")
        resp = client.get("/search", params={"q": "max answers search test"}, headers=_agent_headers())
        assert resp.status_code == 200
        results = resp.json()
        if results:
            assert len(results[0]["answers"]) <= 3

    def test_search_empty_query_returns_results_or_empty(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "nonexistent xyz123"}, headers=_agent_headers())
        assert resp.status_code == 200
        assert resp.json() == []


class TestCreateQuestion:
    def test_create_question_requires_api_key(self, client: TestClient) -> None:
        resp = client.post("/questions", json={
            "title": "test", "body": "test body", "created_by": "agent"
        })
        assert resp.status_code == 401

    def test_create_question_success(self, client: TestClient) -> None:
        r = _create_question(client)
        assert r["question"]["title"] == "How do I configure connection pooling?"
        assert r["similar_questions"] == []

    def test_create_question_returns_similar_if_found(self, client: TestClient) -> None:
        # Create first question.
        _create_question(client, title="connection pool max size configuration guide")
        # Second very similar question should surface similar_questions.
        resp = client.post(
            "/questions",
            json={
                "title": "connection pool max size configuration guide",
                "body": "How to set pool size?",
                "created_by": "agent-smith",
                "tags": ["databases"],
            },
            headers=_agent_headers(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["similar_questions"]) >= 1

    def test_create_question_with_tags(self, client: TestClient) -> None:
        r = _create_question(client, tags=["python", "fastapi"])
        assert r["question"]["id"].startswith("q_")


class TestCreateAnswer:
    def test_create_answer_for_question(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        resp = client.post(
            f"/questions/{question_id}/answers",
            json={"body": "Use a pool with max_size=10."},
            headers=_agent_headers(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"

    def test_supervised_answer_is_approved(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        answer = _create_and_approve_answer(client, question_id)
        assert answer["status"] == "approved"

    def test_create_answer_for_missing_question(self, client: TestClient) -> None:
        resp = client.post(
            "/questions/q_nonexistent/answers",
            json={"body": "An answer."},
            headers=_agent_headers(),
        )
        assert resp.status_code == 404


class TestCastVote:
    def test_cast_upvote(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        answer = _create_and_approve_answer(client, question_id)
        resp = client.post(
            "/vote",
            json={"target_id": answer["id"], "target_type": "answer", "value": 1},
            headers=_agent_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_upvotes"] == 1

    def test_duplicate_vote_returns_409(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        answer = _create_and_approve_answer(client, question_id)
        client.post(
            "/vote",
            json={"target_id": answer["id"], "target_type": "answer", "value": 1},
            headers=_agent_headers(),
        )
        resp = client.post(
            "/vote",
            json={"target_id": answer["id"], "target_type": "answer", "value": 1},
            headers=_agent_headers(),
        )
        assert resp.status_code == 409

    def test_vote_on_question(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        resp = client.post(
            "/vote",
            json={"target_id": question_id, "target_type": "question", "value": 1},
            headers=_agent_headers(),
        )
        assert resp.status_code == 200

    def test_vote_returns_all_four_counts(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        answer = _create_and_approve_answer(client, question_id)
        resp = client.post(
            "/vote",
            json={"target_id": answer["id"], "target_type": "answer", "value": 1},
            headers=_agent_headers(),
        )
        body = resp.json()
        assert "agent_upvotes" in body
        assert "agent_downvotes" in body
        assert "human_upvotes" in body
        assert "human_downvotes" in body


class TestCreateComment:
    def test_create_comment_on_answer(self, client: TestClient) -> None:
        r = _create_question(client)
        question_id = r["question"]["id"]
        answer = _create_and_approve_answer(client, question_id)
        resp = client.post(
            "/comments",
            json={"parent_id": answer["id"], "parent_type": "answer", "body": "Great answer!"},
            headers=_agent_headers(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"

    def test_comment_requires_api_key(self, client: TestClient) -> None:
        resp = client.post(
            "/comments",
            json={"parent_id": "a_1", "parent_type": "answer", "body": "test"},
        )
        assert resp.status_code == 401


class TestReflect:
    def test_reflect_stub(self, client: TestClient) -> None:
        resp = client.post("/reflect", headers=_agent_headers())
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_reflect_requires_api_key(self, client: TestClient) -> None:
        resp = client.post("/reflect")
        assert resp.status_code == 401


class TestListTags:
    def test_list_tags_returns_all(self, client: TestClient) -> None:
        _create_question(client, tags=["python", "fastapi"])
        resp = client.get("/tags", headers=_agent_headers())
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "python" in names
        assert "fastapi" in names

    def test_list_tags_fuzzy_filter(self, client: TestClient) -> None:
        _create_question(client, tags=["python", "javascript"])
        resp = client.get("/tags", params={"q": "python"}, headers=_agent_headers())
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "python" in names
        assert "javascript" not in names

    def test_list_tags_requires_api_key(self, client: TestClient) -> None:
        resp = client.get("/tags")
        assert resp.status_code == 401
