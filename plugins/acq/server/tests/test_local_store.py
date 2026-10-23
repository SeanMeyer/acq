"""Tests for the acq local Q&A store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from acq_mcp.local_store import LocalStore
from acq_mcp.team_client import ApiResult, TeamClient


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

    async def test_offline_thread_arrives_on_the_team_linked_together(self, store: LocalStore) -> None:
        # Everything an agent wrote while the team was unreachable: a question,
        # its answer, and a comment and a vote on that answer.
        q = store.create_question("Q", "B", "a", ["t"])
        a = store.create_answer(q.id, "Answer body", "a")
        c = store.create_comment(a.id, "answer", "Confirmed", "a")
        v = store.cast_vote(a.id, "answer", "a", "agent", 1)
        # Queued children-first, the worst case for ordering.
        for entity_id, kind in ((v.id, "vote"), (c.id, "comment"), (a.id, "answer"), (q.id, "question")):
            store.store.mark_for_drain(entity_id, kind)
        team = FakeTeam()

        async with team.client() as client:
            drained = await store.drain_to_team(client)

        assert drained == 4
        assert store.store.get_pending_drain() == []
        assert set(team.questions) == {q.id}
        assert team.answers == {a.id: q.id}
        assert team.comments == {c.id: a.id}
        assert team.votes == [a.id]
        # Draining only empties the queue; the local copy keeps everything.
        assert (len(store.all_answers()), len(store.all_comments()), len(store.all_votes())) == (1, 1, 1)

    async def test_a_vote_the_team_already_has_leaves_the_queue(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        v = store.cast_vote(q.id, "question", "a", "agent", 1)
        store.store.mark_for_drain(v.id, "vote")
        team = FakeTeam()
        team.questions[q.id] = "Q"
        team.votes.append(q.id)

        async with team.client() as client:
            await store.drain_to_team(client)

        assert team.votes == [q.id]
        assert store.store.get_pending_drain() == []

    async def test_redrain_after_a_lost_response_does_not_duplicate(self, store: LocalStore) -> None:
        q = store.create_question("Q", "B", "a", ["t"])
        a = store.create_answer(q.id, "Answer body", "a")
        store.store.mark_for_drain(q.id, "question")
        store.store.mark_for_drain(a.id, "answer")
        team = FakeTeam()
        # The team stored the question, but the client never saw the response.
        team.questions[q.id] = "Q"

        async with team.client() as client:
            await store.drain_to_team(client)

        assert set(team.questions) == {q.id}
        assert team.answers == {a.id: q.id}
        assert store.store.get_pending_drain() == []


class FakeTeam:
    """In-memory stand-in for the team API's create endpoints, served over HTTP.

    The drain talks to it through a real TeamClient, so what the client puts
    on the wire is part of what the tests check. It keeps the rules the drain
    depends on: the team assigns its own id unless the request carries one, an
    answer to a question it does not hold is a 404, and an id it already holds
    is a replay, not an error. Votes carry no id, so a repeat is a 409.
    """

    def __init__(self) -> None:
        self.questions: dict[str, str] = {}
        self.answers: dict[str, str] = {}
        self.comments: dict[str, str] = {}
        self.votes: list[str] = []
        self._next = 0

    def client(self) -> TeamClient:
        c = TeamClient(base_url="http://team")
        c._client = httpx.AsyncClient(base_url="http://team", transport=httpx.MockTransport(self._handle))
        return c

    def _id(self, prefix: str, body: dict) -> str:
        if body.get("id"):
            return body["id"]
        self._next += 1
        return f"{prefix}_team{self._next}"

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        path = request.url.path
        if path == "/questions":
            qid = self._id("q", body)
            self.questions.setdefault(qid, body["title"])
            return httpx.Response(201, json={"question": {"id": qid}})
        if path.startswith("/questions/") and path.endswith("/answers"):
            question_id = path.split("/")[2]
            if question_id not in self.questions:
                return httpx.Response(404, json={"detail": "Question not found"})
            aid = self._id("a", body)
            self.answers.setdefault(aid, question_id)
            return httpx.Response(201, json={"id": aid})
        if path == "/comments":
            cid = self._id("c", body)
            self.comments.setdefault(cid, body["parent_id"])
            return httpx.Response(201, json={"id": cid})
        if path == "/vote":
            if body["target_id"] in self.votes:
                return httpx.Response(409, json={"detail": "Duplicate vote"})
            self.votes.append(body["target_id"])
            return httpx.Response(200, json={"id": self._id("v", {})})
        return httpx.Response(404)


class TestPullFromTeam:
    @staticmethod
    def _export(next_since: str | None = "server-cursor") -> dict:
        data = {
            "questions": [],
            "answers": [],
            "tags": [],
            "question_tags": [],
            "votes": [],
            "comments": [],
        }
        if next_since is not None:
            data["next_since"] = next_since
        return data

    async def test_returns_server_cursor_on_empty_success(self, store: LocalStore) -> None:
        mock_client = MagicMock()
        mock_client.export_since = AsyncMock(return_value=ApiResult.success(self._export("server-cursor")))

        result = await store.pull_from_team(mock_client, since="previous-cursor")

        assert result is not None
        assert result.count == 0
        assert result.next_since == "server-cursor"
        mock_client.export_since.assert_awaited_once_with(since="previous-cursor")

    async def test_failure_is_distinct_from_empty_success(self, store: LocalStore) -> None:
        mock_client = MagicMock()
        mock_client.export_since = AsyncMock(return_value=ApiResult(error="unreachable", warnings=["unreachable"]))

        assert await store.pull_from_team(mock_client) is None

    async def test_pulling_an_edited_question_keeps_answers_the_team_has_not_seen(
        self, store: LocalStore, tmp_path: Path
    ) -> None:
        """An incremental pull of an edited question must not drop its local-only answers.

        The export re-sends the question's team answers, but not an answer still
        waiting to be drained, so that one survives only if the pull updates the
        question row in place rather than deleting and reinserting it.
        """
        from datetime import UTC, datetime

        from acq_shared.models import Answer, Question
        from acq_shared.sqlite_store import SqliteStore

        team_conn = sqlite3.connect(str(tmp_path / "team.db"))
        team_conn.execute("PRAGMA foreign_keys=ON")
        team = SqliteStore(team_conn)
        q = team.create_question(
            Question(title="Old title", body="b", created_by="a", created_by_type="agent", supervised=True),
            ["db", "stale"],
        )
        team.create_answer(
            Answer(question_id=q.id, body="team answer", created_by="a", created_by_type="agent", supervised=True)
        )
        client = MagicMock()
        client.export_since = AsyncMock(return_value=ApiResult.success(team.export_since(None)))
        await store.pull_from_team(client)

        offline = store.create_answer(q.id, "offline answer", "me", supervised=True)
        store.mark_for_drain(offline.id, "answer")
        cursor = datetime.now(UTC).isoformat()
        team.edit_question(q.id, None, "agent-x", "agent", new_title="New title", new_tags=["db"])
        client.export_since = AsyncMock(return_value=ApiResult.success(team.export_since(cursor)))
        await store.pull_from_team(client, since=cursor)

        thread = store.get_question_thread(q.id)
        assert thread["question"].title == "New title"
        assert sorted(a["answer"].body for a in thread["answers"]) == ["offline answer", "team answer"]
        assert [t["name"] for t in thread["tags"]] == ["db"]
        team.close()

    async def test_old_server_does_not_create_client_cursor(self, store: LocalStore) -> None:
        mock_client = MagicMock()
        mock_client.export_since = AsyncMock(return_value=ApiResult.success(self._export(next_since=None)))

        result = await store.pull_from_team(mock_client)

        assert result is not None
        assert result.next_since is None


class TestConcurrentAccess:
    """One sqlite3 connection is shared across asyncio.to_thread() executor
    threads, so every path that touches it has to hold the store lock. Without
    it these raise InterfaceError, IndexError, or pydantic ValidationError as
    threads corrupt each other's cursor state.
    """

    @staticmethod
    def _seed(store: LocalStore) -> None:
        for i in range(12):
            q = store.create_question(
                f"connection pooling question {i}",
                f"body about sqlite and postgres pooling {i}",
                "agent-1",
                ["sqlite", "postgres", "pooling"],
            )
            store.create_answer(q.id, f"use WAL mode and a bounded pool {i}", "agent-1", supervised=True)

    @pytest.mark.asyncio
    async def test_concurrent_search_is_serialised(self, store: LocalStore) -> None:
        import asyncio

        self._seed(store)
        queries = ["pooling", "sqlite", "postgres", "connection", "WAL", "bounded", "question", "body"]

        for _ in range(8):
            results = await asyncio.gather(
                *(asyncio.to_thread(store.search, q) for q in queries),
                return_exceptions=True,
            )
            failures = [r for r in results if isinstance(r, Exception)]
            assert not failures, f"concurrent search raised: {failures[:3]}"

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations_are_serialised(self, store: LocalStore) -> None:
        import asyncio

        from acq_shared.models import Answer, Question, Vote

        self._seed(store)

        def _ops(n: int):
            q = Question(
                title=f"parallel write {n}",
                body="body text for a parallel write",
                created_by="agent-1",
                created_by_type="agent",
            )
            saved = store.save_question(q, ["parallel"])
            store.mark_for_drain(saved.id, "question")
            store.save_answer(
                Answer(
                    question_id=saved.id,
                    body="an answer written in parallel",
                    created_by="agent-1",
                    created_by_type="agent",
                )
            )
            store.save_vote(
                Vote(
                    target_id=saved.id,
                    target_type="question",
                    voter_id=f"agent-{n}",
                    voter_type="agent",
                    value=1,
                )
            )
            store.get_question_thread(saved.id)
            return store.search("pooling")

        results = await asyncio.gather(
            *(asyncio.to_thread(_ops, n) for n in range(10)),
            return_exceptions=True,
        )
        failures = [r for r in results if isinstance(r, Exception)]
        assert not failures, f"concurrent mixed operations raised: {failures[:3]}"
