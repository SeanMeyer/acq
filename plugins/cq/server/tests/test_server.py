"""Tests for the acq MCP server tools."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from acq_mcp import server
from acq_mcp.server import (
    _do_drain,
    answer,
    ask,
    comment,
    reflect,
    search,
    status,
    vote,
)


@pytest.fixture(autouse=True)
def _reset_server_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide a fresh local store and no team client for each test."""
    monkeypatch.setenv("ACQ_LOCAL_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ACQ_TEAM_ADDR", "")
    monkeypatch.setenv("ACQ_AGENT_NAME", "test-agent")
    server._close_store()
    server._team_client = None
    server._drain_done = False
    yield
    server._close_store()
    server._team_client = None
    server._drain_done = False


def _make_mock_team_client(
    *,
    health: bool = True,
    search_result=None,
    create_question_result=None,
    create_answer_result=None,
    cast_vote_result=None,
    create_comment_result=None,
    get_status_result=None,
) -> MagicMock:
    mock = MagicMock()
    mock.health = AsyncMock(return_value=health)
    mock.search = AsyncMock(return_value=search_result)
    mock.create_question = AsyncMock(return_value=create_question_result)
    mock.create_answer = AsyncMock(return_value=create_answer_result)
    mock.cast_vote = AsyncMock(return_value=cast_vote_result)
    mock.create_comment = AsyncMock(return_value=create_comment_result)
    mock.get_status = AsyncMock(return_value=get_status_result)
    mock.base_url = "http://localhost:8742"
    return mock


class TestSearch:
    async def test_returns_empty_no_data(self) -> None:
        result = await search(query="anything")
        assert result["results"] == []
        assert result["source"] == "local"

    async def test_local_fallback_when_no_team(self) -> None:
        store = server._get_store()
        q = store.create_question("How to pool connections?", "body", "a", ["db"])
        result = await search(query="pool connections")
        assert len(result["results"]) == 1
        assert result["source"] == "local"

    async def test_uses_team_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            search_result=[{"id": "q_team_1", "title": "Team question"}]
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="any")
        assert result["source"] == "team"
        assert len(result["results"]) == 1

    async def test_merges_team_and_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        store.create_question("Local question about python", "body", "a", ["python"])

        mock = _make_mock_team_client(
            search_result=[{"id": "q_team_1", "title": "Team result about python"}]
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="python")
        assert result["source"] == "both"
        assert len(result["results"]) == 2

    async def test_deduplicates_by_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        q = store.create_question("Local question about sqlite", "body", "a", ["sqlite"])

        # Team returns same ID as local
        mock = _make_mock_team_client(
            search_result=[{"id": q.id, "title": "Same question"}]
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="sqlite")
        ids = [r["id"] for r in result["results"]]
        assert len(ids) == len(set(ids))

    async def test_respects_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            search_result=[{"id": f"q_{i}", "title": f"Q {i}"} for i in range(10)]
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="q", limit=3)
        assert len(result["results"]) <= 3

    async def test_falls_back_to_local_when_team_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        store.create_question("Question about caching", "body", "a", ["cache"])

        mock = _make_mock_team_client(search_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="caching")
        assert result["source"] == "local"


class TestAsk:
    async def test_creates_question_locally(self) -> None:
        result = await ask(title="How do I pool?", body="Need details", tags=["db"])
        assert result["action"] == "created"
        assert result["question_id"].startswith("q_")
        assert result.get("source") == "local"

    async def test_blank_title_returns_error(self) -> None:
        result = await ask(title="  ", body="Body", tags=["t"])
        assert "error" in result

    async def test_blank_body_returns_error(self) -> None:
        result = await ask(title="Title", body="", tags=["t"])
        assert "error" in result

    async def test_empty_tags_returns_error(self) -> None:
        result = await ask(title="Title", body="Body", tags=[])
        assert "error" in result

    async def test_uses_team_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            create_question_result={"id": "q_team_1", "similar_questions": []}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "created"
        assert result["question_id"] == "q_team_1"

    async def test_returns_similar_found_when_duplicates_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        similar = [{"id": "q_existing", "title": "Existing question", "similarity": 0.9}]
        mock = _make_mock_team_client(
            create_question_result={"similar_questions": similar}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "similar_found"
        assert len(result["similar_questions"]) == 1

    async def test_force_create_bypasses_similar_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        similar = [{"id": "q_existing", "title": "Existing question", "similarity": 0.9}]
        mock = _make_mock_team_client(
            create_question_result={"id": "q_new", "similar_questions": similar}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"], force_create=True)
        assert result["action"] == "created"

    async def test_falls_back_to_local_when_team_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(create_question_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "created"
        assert result.get("source") == "local"


class TestAnswer:
    async def test_creates_answer_locally(self) -> None:
        store = server._get_store()
        q = store.create_question("Q", "B", "a", ["t"])
        result = await answer(question_id=q.id, body="My answer")
        assert result["answer_id"].startswith("a_")
        assert result.get("source") == "local"

    async def test_blank_body_returns_error(self) -> None:
        result = await answer(question_id="q_1", body="  ")
        assert "error" in result

    async def test_uses_team_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            create_answer_result={"id": "a_team_1", "status": "pending"}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await answer(question_id="q_1", body="Answer")
        assert result["answer_id"] == "a_team_1"

    async def test_falls_back_to_local_when_team_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        q = store.create_question("Q", "B", "a", ["t"])

        mock = _make_mock_team_client(create_answer_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await answer(question_id=q.id, body="Answer")
        assert result["answer_id"].startswith("a_")
        assert result.get("source") == "local"


class TestVote:
    async def test_invalid_value_returns_error(self) -> None:
        result = await vote(target_id="q_1", value=0)
        assert "error" in result

    async def test_casts_vote_locally(self) -> None:
        result = await vote(target_id="q_1", value=1)
        assert "vote_id" in result
        assert result.get("source") == "local"

    async def test_uses_team_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            cast_vote_result={"upvotes": 5, "downvotes": 0}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert result["upvotes"] == 5

    async def test_handles_409_already_voted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            cast_vote_result={"error": "Already voted", "status_code": 409}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert "error" in result
        assert "Already voted" in result["error"]

    async def test_handles_429_rate_limited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            cast_vote_result={"error": "Rate limited", "status_code": 429}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    async def test_falls_back_to_local_when_team_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(cast_vote_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert "vote_id" in result
        assert result.get("source") == "local"


class TestComment:
    async def test_creates_comment_locally(self) -> None:
        result = await comment(parent_id="q_1", body="Great question!")
        assert result["comment_id"].startswith("c_")
        assert result.get("source") == "local"

    async def test_blank_body_returns_error(self) -> None:
        result = await comment(parent_id="q_1", body="")
        assert "error" in result

    async def test_uses_team_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            create_comment_result={"id": "c_team_1", "status": "pending"}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await comment(parent_id="q_1", body="Comment body")
        assert result["comment_id"] == "c_team_1"

    async def test_falls_back_to_local_when_team_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(create_comment_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await comment(parent_id="q_1", body="Comment")
        assert result["comment_id"].startswith("c_")
        assert result.get("source") == "local"


class TestReflect:
    async def test_returns_message_with_guidance(self) -> None:
        result = await reflect(session_context="I discovered a bug in the payment API.")
        assert "message" in result
        assert result["status"] == "stub"
        assert "ask" in result["message"] or "answer" in result["message"]

    async def test_empty_context_returns_message(self) -> None:
        result = await reflect(session_context="   ")
        assert "message" in result
        assert result["status"] == "stub"
        assert "empty" in result["message"].lower()


class TestStatus:
    async def test_returns_local_stats(self) -> None:
        result = await status()
        assert "local" in result
        assert result["local"]["questions"] == 0
        assert result["team"] == {"status": "not_configured"}

    async def test_counts_after_operations(self) -> None:
        store = server._get_store()
        q = store.create_question("Q", "B", "a", ["t1", "t2"])
        store.create_answer(q.id, "A", "a")

        result = await status()
        assert result["local"]["questions"] == 1
        assert result["local"]["answers"] == 1
        assert result["local"]["tags"] == 2

    async def test_team_ok_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(health=True, get_status_result={"questions": 100})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await status()
        assert result["team"]["status"] == "ok"
        assert result["team"]["url"] == "http://localhost:8742"
        assert result["team_stats"]["questions"] == 100

    async def test_team_unreachable_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(health=False)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await status()
        assert result["team"]["status"] == "unreachable"


class TestDrainOnStartup:
    async def test_drain_moves_local_to_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        mock = _make_mock_team_client(
            create_question_result={"id": "q_team_1"},
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        assert len(store.all_questions()) == 0
        assert server._drain_done is True

    async def test_drain_skips_when_no_team(self) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        await _do_drain()

        assert len(store.all_questions()) == 1

    async def test_drain_skips_when_team_unhealthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        mock = _make_mock_team_client(health=False)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        assert len(store.all_questions()) == 1

    async def test_drain_runs_only_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = _make_mock_team_client(
            create_question_result={"id": "q_team_1"}
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()
        await _do_drain()

        # health() called only once — drain was skipped on second call
        assert mock.health.call_count == 1

    async def test_drain_keeps_content_on_team_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        mock = _make_mock_team_client(create_question_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        assert len(store.all_questions()) == 1


class TestEndToEnd:
    async def test_ask_answer_search_lifecycle(self) -> None:
        # Ask a question locally.
        asked = await ask(
            title="How do I configure SQLite WAL mode?",
            body="I need better write concurrency.",
            tags=["sqlite", "performance"],
            language="python",
        )
        assert asked["action"] == "created"
        qid = asked["question_id"]

        # Answer the question.
        answered = await answer(question_id=qid, body="Use PRAGMA journal_mode=WAL")
        assert "answer_id" in answered

        # Search finds the question.
        results = await search(query="SQLite WAL mode")
        assert len(results["results"]) == 1
        assert results["results"][0]["id"] == qid

    async def test_comment_and_vote_stored_locally(self) -> None:
        c = await comment(parent_id="q_123", body="Interesting question!")
        assert c["comment_id"].startswith("c_")

        v = await vote(target_id="q_123", value=1)
        assert v["vote_id"].startswith("v_")
