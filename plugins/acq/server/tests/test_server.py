"""Tests for the acq MCP server tools."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from acq_mcp import server
from acq_mcp.server import (
    _do_drain,
    _do_pull,
    answer,
    ask,
    comment,
    reflect,
    search,
    status,
    vote,
)
from acq_mcp.team_client import ApiResult


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


def _to_api_result(value) -> ApiResult:
    """Convert a test value to an ApiResult.

    - None → transport error (simulates unreachable team API)
    - dict with "error" key → HTTP error with status_code
    - anything else → success
    """
    if value is None:
        return ApiResult(error="Team API unreachable", warnings=["Team API unreachable"])
    if isinstance(value, dict) and "error" in value:
        return ApiResult(
            error=value["error"],
            status_code=value.get("status_code", 0),
            warnings=[value["error"]],
        )
    return ApiResult.success(value)


def _make_mock_team_client(
    *,
    health: bool = True,
    search_result=None,
    create_question_result=None,
    create_answer_result=None,
    cast_vote_result=None,
    create_comment_result=None,
    get_status_result=None,
    export_since_result=None,
) -> MagicMock:
    mock = MagicMock()
    mock.health = AsyncMock(return_value=health)
    mock.search = AsyncMock(return_value=_to_api_result(search_result))
    mock.create_question = AsyncMock(return_value=_to_api_result(create_question_result))
    mock.create_answer = AsyncMock(return_value=_to_api_result(create_answer_result))
    mock.cast_vote = AsyncMock(return_value=_to_api_result(cast_vote_result))
    mock.create_comment = AsyncMock(return_value=_to_api_result(create_comment_result))
    mock.get_status = AsyncMock(return_value=_to_api_result(get_status_result))
    mock.export_since = AsyncMock(return_value=_to_api_result(export_since_result))
    mock.base_url = "http://localhost:8742"
    return mock


class TestSearch:
    async def test_returns_empty_no_data(self) -> None:
        result = await search(query="anything")
        assert result["results"] == []
        assert result["source"] == "local"

    async def test_pending_question_absent_from_search(self) -> None:
        """An agent question awaiting review must not surface in search."""
        store = server._get_store()
        store.create_question("How to pool connections?", "body", "a", ["db"], supervised=False)
        result = await search(query="pool connections")
        assert result["results"] == []
        assert result["source"] == "local"

    async def test_supervised_question_found_by_search(self) -> None:
        """The mirror image: a vouched-for question goes live and is searchable."""
        store = server._get_store()
        store.create_question("How to pool connections?", "body", "a", ["db"], supervised=True)
        result = await search(query="pool connections")
        assert len(result["results"]) == 1
        assert result["source"] == "local"

    async def test_search_uses_local_store_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Search should NEVER call the team API — local only."""
        store = server._get_store()
        store.create_question("Question about caching", "body", "a", ["cache"], supervised=True)

        mock = _make_mock_team_client(search_result=[{"id": "q_team_1", "title": "Team question"}])
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await search(query="caching")
        assert result["source"] == "local"
        # Team search must NOT be called
        mock.search.assert_not_called()

    async def test_search_returns_results_from_local(self) -> None:
        store = server._get_store()
        store.create_question("Local question about python", "body", "a", ["python"], supervised=True)

        result = await search(query="python")
        assert result["source"] == "local"
        assert len(result["results"]) >= 1


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

    async def test_ask_writes_to_team_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(
            create_question_result={
                "question": {
                    "id": "q_team_1",
                    "title": "Q",
                    "body": "B",
                    "created_by": "test-agent",
                    "created_by_type": "agent",
                    "status": "open",
                },
                "similar_questions": [],
            }
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "created"
        assert result["question_id"] == "q_team_1"
        assert result["source"] == "team"
        mock.create_question.assert_called_once()

    async def test_ask_forwards_supervised_to_team(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(create_question_result={"question": {"id": "q_team_1"}, "similar_questions": []})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await ask(title="Q", body="B", tags=["t"], supervised=True)

        assert mock.create_question.call_args.kwargs["supervised"] is True

    async def test_ask_falls_back_to_local_on_team_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(create_question_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "created"
        assert result.get("source") == "local"
        assert result["question_id"].startswith("q_")

    async def test_local_fallback_question_stays_pending(self) -> None:
        result = await ask(title="Q", body="B", tags=["t"])

        (q,) = server._get_store().all_questions()
        assert q.id == result["question_id"]
        assert q.supervised is False
        assert q.status == "pending"

    async def test_local_fallback_supervised_question_goes_live(self) -> None:
        result = await ask(title="Q", body="B", tags=["t"], supervised=True)

        (q,) = server._get_store().all_questions()
        assert q.id == result["question_id"]
        assert q.supervised is True
        assert q.status == "open"

    async def test_returns_similar_found_when_duplicates_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        similar = [{"id": "q_existing", "title": "Existing question", "similarity": 0.9}]
        mock = _make_mock_team_client(create_question_result={"similar_questions": similar})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"])
        assert result["action"] == "similar_found"
        assert len(result["similar_questions"]) == 1

    async def test_force_create_bypasses_similar_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        similar = [{"id": "q_existing", "title": "Existing question", "similarity": 0.9}]
        mock = _make_mock_team_client(create_question_result={"id": "q_new", "similar_questions": similar})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await ask(title="Q", body="B", tags=["t"], force_create=True)
        assert result["action"] == "created"


class TestAnswer:
    async def test_creates_answer_locally(self) -> None:
        store = server._get_store()
        store.create_question("Q", "B", "a", ["t"], supervised=True)
        # Get the question to use its ID
        qs = store.all_questions()
        result = await answer(question_id=qs[0].id, body="My answer")
        assert result["answer_id"].startswith("a_")
        assert result.get("source") == "local"

    async def test_blank_body_returns_error(self) -> None:
        result = await answer(question_id="q_1", body="  ")
        assert "error" in result

    async def test_answer_write_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When team API succeeds, answer is written to team first, then local."""
        mock = _make_mock_team_client(
            create_answer_result={
                "id": "a_team_1",
                "question_id": "q_1",
                "body": "Answer",
                "created_by": "test-agent",
                "created_by_type": "agent",
                "status": "pending",
                "supervised": False,
            }
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await answer(question_id="q_1", body="Answer")
        assert result["answer_id"] == "a_team_1"
        assert result.get("source") == "team"

        # Verify team API was called
        mock.create_answer.assert_called_once()

    async def test_falls_back_to_local_when_team_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = server._get_store()
        store.create_question("Q", "B", "a", ["t"])
        qs = store.all_questions()

        mock = _make_mock_team_client(create_answer_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await answer(question_id=qs[0].id, body="Answer")
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

    async def test_uses_team_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(cast_vote_result={"upvotes": 5, "downvotes": 0})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert result["upvotes"] == 5

    async def test_handles_409_already_voted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(cast_vote_result={"error": "Already voted", "status_code": 409})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert "error" in result
        assert "Already voted" in result["error"]

    async def test_handles_429_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(cast_vote_result={"error": "Rate limited", "status_code": 429})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await vote(target_id="q_1", value=1)
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    async def test_falls_back_to_local_when_team_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    async def test_uses_team_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(
            create_comment_result={
                "id": "c_team_1",
                "parent_id": "q_1",
                "parent_type": "question",
                "body": "Comment body",
                "created_by": "test-agent",
                "created_by_type": "agent",
                "status": "pending",
            }
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await comment(parent_id="q_1", body="Comment body")
        assert result["comment_id"] == "c_team_1"
        assert result.get("source") == "team"

    async def test_falls_back_to_local_when_team_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert result["team"] == {"status": "not_configured"}

    async def test_counts_after_operations(self) -> None:
        store = server._get_store()
        store.create_question("Q", "B", "a", ["t1", "t2"])
        qs = store.all_questions()
        store.create_answer(qs[0].id, "A", "a")

        result = await status()
        assert result["local"]["total_questions"] == 1

    async def test_team_ok_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(health=True, get_status_result={"questions": 100})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await status()
        assert result["team"]["status"] == "ok"
        assert result["team"]["url"] == "http://localhost:8742"
        assert result["team_stats"]["questions"] == 100

    async def test_team_unreachable_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(health=False)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        result = await status()
        assert result["team"]["status"] == "unreachable"


class TestDrainOnStartup:
    async def test_drain_moves_local_to_team(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = server._get_store()
        q = store.create_question("Local Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")

        mock = _make_mock_team_client(
            create_question_result={"id": q.id},
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        # Content stays in local (read replica) but drain queue is cleared
        assert len(store.all_questions()) == 1
        assert len(store.store.get_pending_drain()) == 0
        assert server._drain_done is True

    async def test_drain_skips_when_no_team(self) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        await _do_drain()

        assert len(store.all_questions()) == 1

    async def test_drain_skips_when_team_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = server._get_store()
        store.create_question("Local Q", "B", "a", ["t"])

        mock = _make_mock_team_client(health=False)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        assert len(store.all_questions()) == 1

    async def test_drain_runs_only_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(create_question_result={"id": "q_team_1"})
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()
        await _do_drain()

        # health() called only once — drain was skipped on second call
        assert mock.health.call_count == 1

    async def test_drain_keeps_pending_on_team_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = server._get_store()
        q = store.create_question("Local Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")

        mock = _make_mock_team_client(create_question_result=None)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_drain()

        assert len(store.all_questions()) == 1
        assert len(store.store.get_pending_drain()) == 1  # still pending


class TestPullSync:
    async def test_pull_sync_populates_local_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock team_client.export_since, verify local store gets populated."""
        export_data = {
            "questions": [
                {
                    "id": "q_remote_1",
                    "title": "Remote Question",
                    "body": "From team API",
                    "created_by": "remote-agent",
                    "created_by_type": "agent",
                    "status": "open",
                }
            ],
            "answers": [],
            "tags": [],
            "question_tags": [],
            "votes": [],
            "comments": [],
        }
        mock = _make_mock_team_client(
            health=True,
            export_since_result=export_data,
        )
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_pull()

        mock.export_since.assert_called_once_with(since=None)

        # Verify the local store now has the question
        store = server._get_store()
        qs = store.all_questions()
        assert len(qs) == 1
        assert qs[0].id == "q_remote_1"
        assert qs[0].title == "Remote Question"

    async def test_pull_skips_when_no_team(self) -> None:
        await _do_pull()
        store = server._get_store()
        assert len(store.all_questions()) == 0

    async def test_pull_skips_when_team_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = _make_mock_team_client(health=False)
        monkeypatch.setattr(server, "_get_team_client", lambda: mock)

        await _do_pull()

        mock.export_since.assert_not_called()


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

        # The answer stays bundled with the pending question until review.
        answered = await answer(question_id=qid, body="Use PRAGMA journal_mode=WAL")
        assert "answer_id" in answered
        assert (await search(query="SQLite WAL mode"))["results"] == []

        server._get_store().store.approve_content(qid)
        results = await search(query="SQLite WAL mode")
        assert len(results["results"]) == 1
        assert results["results"][0]["id"] == qid

    async def test_comment_and_vote_stored_locally(self) -> None:
        c = await comment(parent_id="q_123", body="Interesting question!")
        assert c["comment_id"].startswith("c_")

        v = await vote(target_id="q_123", value=1)
        assert v["vote_id"].startswith("v_")
