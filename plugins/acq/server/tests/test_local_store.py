"""Tests for the acq local Q&A store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from acq_mcp.local_store import LocalStore
from acq_mcp.team_client import ApiResult


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[LocalStore]:
    s = LocalStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


class TestInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "subdir" / "nested" / "test.db"
        s = LocalStore(db_path=db_path)
        s.close()
        assert db_path.exists()

    def test_creates_expected_tables(self, store: LocalStore) -> None:
        conn = sqlite3.connect(str(store.db_path))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        conn.close()
        table_names = {r[0] for r in rows}
        assert "questions" in table_names
        assert "answers" in table_names
        assert "votes" in table_names
        assert "comments" in table_names
        assert "tags" in table_names

    def test_idempotent_schema_creation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        s1 = LocalStore(db_path=db_path)
        s1.close()
        s2 = LocalStore(db_path=db_path)
        s2.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        with LocalStore(db_path=tmp_path / "test.db") as s:
            q = s.create_question("Q", "body", "agent-1", ["tag"])
            assert q.id.startswith("q_")

    def test_close_is_idempotent(self, store: LocalStore) -> None:
        store.close()
        store.close()


class TestCreateQuestion:
    def test_creates_and_returns_question(self, store: LocalStore) -> None:
        q = store.create_question("How do I use FTS5?", "body text", "agent-1", ["sqlite"])
        assert q.id.startswith("q_")
        assert q.title == "How do I use FTS5?"
        assert q.created_by == "agent-1"

    def test_stores_tags(self, store: LocalStore) -> None:
        store.create_question("Q", "B", "agent-1", ["python", "sqlite"])
        conn = sqlite3.connect(str(store.db_path))
        count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        conn.close()
        assert count == 2

    def test_stores_context_fields(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "agent-1", [], language="python", framework="django", pattern="web-api")
        assert q.context_language == "python"
        assert q.context_framework == "django"
        assert q.context_pattern == "web-api"

    def test_normalizes_tag_names(self, store: LocalStore) -> None:
        store.create_question("Q", "B", "agent-1", ["  Python  ", "SQLITE"])
        conn = sqlite3.connect(str(store.db_path))
        rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        conn.close()
        names = [r[0] for r in rows]
        assert "python" in names
        assert "sqlite" in names

    def test_upserts_existing_tags(self, store: LocalStore) -> None:
        store.create_question("Q1", "B", "agent-1", ["python"])
        store.create_question("Q2", "B", "agent-1", ["python"])
        conn = sqlite3.connect(str(store.db_path))
        row = conn.execute("SELECT usage_count FROM tags WHERE name='python'").fetchone()
        conn.close()
        assert row[0] == 2

    def test_indexes_in_fts(self, store: LocalStore) -> None:
        store.create_question("connection pooling howto", "configure pool", "a", ["db"])
        results = store.search("connection pooling")
        assert len(results) == 1
        q = results[0]["question"]
        title = q.title if hasattr(q, "title") else q["title"]
        assert "pooling" in title.lower()


class TestCreateAnswer:
    def test_creates_answer(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        a = store.create_answer(q.id, "Answer body", "agent-1")
        assert a.id.startswith("a_")
        assert a.question_id == q.id
        assert a.status == "pending"

    def test_supervised_flag(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        a = store.create_answer(q.id, "Body", "agent-1", supervised=True)
        assert a.supervised is True

    def test_indexes_in_fts(self, store: LocalStore) -> None:
        q = store.create_question("How to configure SQLite?", "need help", "a", ["sqlite"])
        store.create_answer(q.id, "Use WAL mode for better concurrency", "agent-1")
        results = store.search("WAL mode")
        assert len(results) == 1


class TestCastVote:
    def test_casts_vote(self, store: LocalStore) -> None:
        v = store.cast_vote("q_123", "question", "agent-1", "agent", 1)
        assert v.id.startswith("v_")
        assert v.value == 1

    def test_casts_downvote(self, store: LocalStore) -> None:
        v = store.cast_vote("q_123", "question", "agent-1", "agent", -1)
        assert v.value == -1

    def test_duplicate_vote_detected(self, store: LocalStore) -> None:
        store.cast_vote("q_123", "question", "agent-1", "agent", 1)
        # SqliteStore detects duplicates and returns error dict instead of raising
        store.cast_vote("q_123", "question", "agent-1", "agent", 1)
        # The second call still returns a Vote model from the wrapper,
        # but the underlying SqliteStore returned an error dict.
        # Either way, only one vote should exist.
        assert len(store.all_votes()) == 1


class TestCreateComment:
    def test_creates_comment(self, store: LocalStore) -> None:
        c = store.create_comment("q_123", "question", "This is helpful", "agent-1")
        assert c.id.startswith("c_")
        assert c.body == "This is helpful"
        assert c.status == "pending"

    def test_supervised_flag(self, store: LocalStore) -> None:
        c = store.create_comment("q_123", "question", "B", "a", supervised=True)
        assert c.supervised is True


class TestSearch:
    def test_returns_empty_for_no_match(self, store: LocalStore) -> None:
        store.create_question("Python tips", "body", "a", ["python"])
        results = store.search("completely unrelated xyzzy")
        assert results == []

    def test_fts_finds_by_title(self, store: LocalStore) -> None:
        store.create_question("How to use connection pooling", "body", "a", ["db"])
        results = store.search("connection pooling")
        assert len(results) == 1

    def test_fts_finds_by_body(self, store: LocalStore) -> None:
        store.create_question("DB question", "WAL mode improves concurrency", "a", ["db"])
        results = store.search("WAL mode")
        assert len(results) == 1

    def test_respects_limit(self, store: LocalStore) -> None:
        for i in range(5):
            store.create_question(f"Question {i} about python", "body", "a", ["python"])
        results = store.search("python", limit=3)
        assert len(results) <= 3

    def test_returns_top_answer(self, store: LocalStore) -> None:
        q = store.create_question("How to pool DB connections?", "body", "a", ["db"])
        # supervised=True so the answer is auto-approved and visible in search
        store.create_answer(q.id, "Use pgBouncer", "agent-1", supervised=True)
        results = store.search("pool DB connections")
        assert len(results) == 1
        # SqliteStore returns thread dicts: {"question": Q, "answers": [...], "comments": [...]}
        answers = results[0]["answers"]
        assert len(answers) >= 1
        first_answer = answers[0]["answer"]
        body = first_answer.body if hasattr(first_answer, "body") else first_answer["body"]
        assert "pgBouncer" in body

    def test_returns_answer_count(self, store: LocalStore) -> None:
        q = store.create_question("How to use SQLite FTS?", "body", "a", ["sqlite"])
        # supervised=True so answers are auto-approved and visible in search
        store.create_answer(q.id, "Answer 1", "a", supervised=True)
        store.create_answer(q.id, "Answer 2", "a", supervised=True)
        results = store.search("SQLite FTS")
        assert len(results[0]["answers"]) == 2

    def test_empty_query_returns_empty(self, store: LocalStore) -> None:
        store.create_question("Python tips", "body", "a", ["python"])
        results = store.search("")
        assert results == []


class TestGetStatus:
    def test_empty_store(self, store: LocalStore) -> None:
        s = store.get_status()
        assert s["total_questions"] == 0
        assert s["total_answers"] == 0
        assert s["total_tags"] == 0
        assert s["total_votes"] == 0

    def test_counts_after_inserts(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["tag1", "tag2"])
        store.create_answer(q.id, "A", "a")
        store.cast_vote(q.id, "question", "a", "agent", 1)
        s = store.get_status()
        assert s["total_questions"] == 1
        assert s["total_tags"] == 2
        assert s["total_votes"] == 1


class TestAllMethods:
    def test_all_questions(self, store: LocalStore) -> None:
        store.create_question("Q1", "B", "a", ["t"])
        store.create_question("Q2", "B", "a", ["t"])
        assert len(store.all_questions()) == 2

    def test_all_answers(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        store.create_answer(q.id, "A1", "a")
        store.create_answer(q.id, "A2", "a")
        assert len(store.all_answers()) == 2

    def test_all_votes(self, store: LocalStore) -> None:
        store.cast_vote("q_1", "question", "a", "agent", 1)
        store.cast_vote("q_2", "question", "b", "agent", -1)
        assert len(store.all_votes()) == 2

    def test_all_comments(self, store: LocalStore) -> None:
        store.create_comment("q_1", "question", "C1", "a")
        store.create_comment("q_2", "question", "C2", "a")
        assert len(store.all_comments()) == 2

    def test_all_empty(self, store: LocalStore) -> None:
        assert store.all_questions() == []
        assert store.all_answers() == []
        assert store.all_votes() == []
        assert store.all_comments() == []


class TestDrainToTeam:
    async def test_drain_pushes_pending_questions(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")

        mock_client = MagicMock()
        mock_client.create_question = AsyncMock(return_value=ApiResult.success({"id": q.id}))

        drained = await store.drain_to_team(mock_client)

        assert drained == 1
        mock_client.create_question.assert_called_once()
        # Content stays in local (read replica) but drain queue is cleared
        assert len(store.all_questions()) == 1
        assert len(store.store.get_pending_drain()) == 0

    async def test_drain_skips_content_not_marked(self, store: LocalStore) -> None:
        """Content from bulk_upsert (team sync) is NOT marked for drain."""
        store.create_question("Q", "B", "a", ["t"])
        # Not marked for drain — should not be pushed to team

        mock_client = MagicMock()
        mock_client.create_question = AsyncMock(return_value=ApiResult.success({"id": "q_team_1"}))

        drained = await store.drain_to_team(mock_client)

        assert drained == 0
        mock_client.create_question.assert_not_called()

    async def test_drain_keeps_pending_on_team_error(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")

        mock_client = MagicMock()
        mock_client.create_question = AsyncMock(return_value=ApiResult(error="unreachable", warnings=["unreachable"]))

        drained = await store.drain_to_team(mock_client)

        assert drained == 0
        assert len(store.store.get_pending_drain()) == 1  # still pending

    async def test_drain_handles_exception_gracefully(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")

        mock_client = MagicMock()
        mock_client.create_question = AsyncMock(side_effect=Exception("network error"))

        drained = await store.drain_to_team(mock_client)

        assert drained == 0
        assert len(store.store.get_pending_drain()) == 1

    async def test_drain_pushes_answers(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        store.store.mark_for_drain(q.id, "question")
        a = store.create_answer(q.id, "Answer body", "a")
        store.store.mark_for_drain(a.id, "answer")

        mock_client = MagicMock()
        mock_client.create_question = AsyncMock(return_value=ApiResult.success({"id": q.id}))
        mock_client.create_answer = AsyncMock(return_value=ApiResult.success({"id": a.id}))

        drained = await store.drain_to_team(mock_client)

        assert drained == 2
        assert len(store.store.get_pending_drain()) == 0

    async def test_drain_pushes_votes_and_comments(self, store: LocalStore) -> None:
        v = store.cast_vote("q_123", "question", "a", "agent", 1)
        store.store.mark_for_drain(v.id, "vote")
        c = store.create_comment("q_123", "question", "Nice question", "a")
        store.store.mark_for_drain(c.id, "comment")

        mock_client = MagicMock()
        mock_client.cast_vote = AsyncMock(return_value=ApiResult.success({"id": v.id}))
        mock_client.create_comment = AsyncMock(return_value=ApiResult.success({"id": c.id}))

        drained = await store.drain_to_team(mock_client)

        assert drained == 2
        assert len(store.store.get_pending_drain()) == 0
        # Content stays in local (read replica), only drain queue is cleared
        assert len(store.all_votes()) == 1
        assert len(store.all_comments()) == 1
