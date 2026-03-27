"""Tests for the ACQ team store (Q&A model) using SqliteStore."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from acq_shared.models import Answer, Comment, Question, Tag, Vote
from acq_shared.sqlite_store import SqliteStore


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    return c


@pytest.fixture()
def store(conn: sqlite3.Connection) -> SqliteStore:
    return SqliteStore(conn)


def _make_question(**overrides) -> Question:
    defaults = {
        "title": "How do I use connection pooling?",
        "body": "I want to configure a connection pool.",
        "created_by": "agent-1",
        "created_by_type": "agent",
    }
    return Question(**{**defaults, **overrides})


def _make_answer(question_id: str, **overrides) -> Answer:
    defaults = {
        "question_id": question_id,
        "body": "Use a pool with max_size=10.",
        "created_by": "agent-1",
        "created_by_type": "agent",
    }
    return Answer(**{**defaults, **overrides})


def _make_comment(parent_id: str, parent_type: str = "answer", **overrides) -> Comment:
    defaults = {
        "parent_id": parent_id,
        "parent_type": parent_type,
        "body": "Great answer!",
        "created_by": "agent-1",
        "created_by_type": "agent",
    }
    return Comment(**{**defaults, **overrides})


def _make_vote(target_id: str, target_type: str = "answer", **overrides) -> Vote:
    defaults = {
        "target_id": target_id,
        "target_type": target_type,
        "voter_id": "agent-1",
        "voter_type": "agent",
        "value": 1,
    }
    return Vote(**{**defaults, **overrides})


class TestCreateQuestion:
    def test_create_stores_question(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, ["databases", "performance"])
        retrieved = store.get_question(q.id)
        assert retrieved is not None
        assert retrieved.id == q.id
        assert retrieved.title == q.title

    def test_create_inserts_tags(self, store: SqliteStore, conn: sqlite3.Connection) -> None:
        q = _make_question()
        store.create_question(q, ["python", "fastapi"])
        rows = conn.execute(
            "SELECT t.name FROM tags t JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ?",
            (q.id,),
        ).fetchall()
        names = {r[0] for r in rows}
        assert names == {"python", "fastapi"}

    def test_create_indexes_in_fts(self, store: SqliteStore, conn: sqlite3.Connection) -> None:
        q = _make_question(title="unique fts title abc")
        store.create_question(q, [])
        rows = conn.execute(
            "SELECT entity_id FROM search_index WHERE search_index MATCH 'unique'",
        ).fetchall()
        assert any(r[0] == q.id for r in rows)


class TestCreateAnswer:
    def test_answer_pending_by_default(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        result = store.create_answer(a)
        assert result.status == "pending"

    def test_supervised_answer_auto_approved(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        result = store.create_answer(a)
        assert result.status == "approved"

    def test_answer_indexed_in_fts(self, store: SqliteStore, conn: sqlite3.Connection) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, body="unique pool term zxqw")
        store.create_answer(a)
        rows = conn.execute(
            "SELECT entity_id FROM search_index WHERE search_index MATCH 'unique'",
        ).fetchall()
        assert any(r[0] == a.id for r in rows)


class TestCreateComment:
    def test_human_comment_auto_approved(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        c = _make_comment(a.id, created_by_type="human", created_by="alice")
        result = store.create_comment(c)
        assert result.status == "approved"

    def test_agent_comment_pending(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        c = _make_comment(a.id)
        result = store.create_comment(c)
        assert result.status == "pending"


class TestCastVote:
    def test_cast_vote_returns_counts(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        result = store.cast_vote(_make_vote(a.id))
        assert result["agent_upvotes"] == 1
        assert result["agent_downvotes"] == 0

    def test_duplicate_vote_rejected(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        store.cast_vote(_make_vote(a.id))
        result = store.cast_vote(_make_vote(a.id))
        assert result["error"] == "duplicate_vote"

    def test_vote_on_question(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        result = store.cast_vote(_make_vote(q.id, target_type="question"))
        assert "agent_upvotes" in result
        assert result["agent_upvotes"] == 1

    def test_denormalized_counts_updated(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        store.cast_vote(_make_vote(a.id, voter_id="v1"))
        store.cast_vote(_make_vote(a.id, voter_id="v2", value=-1, voter_type="human"))
        retrieved = store.get_answer(a.id)
        assert retrieved.agent_upvotes == 1
        assert retrieved.human_downvotes == 1

    def test_vote_is_immutable(self, store: SqliteStore) -> None:
        """Once a vote is cast, it cannot be changed (duplicate returns error)."""
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        store.cast_vote(_make_vote(a.id, value=1))
        result = store.cast_vote(_make_vote(a.id, value=-1))
        assert "error" in result


class TestSearch:
    def test_returns_approved_answers_only(self, store: SqliteStore) -> None:
        q = _make_question(title="connection pool configuration guide")
        store.create_question(q, [])
        pending_a = _make_answer(q.id, body="pending answer here")
        approved_a = _make_answer(q.id, body="approved answer here", supervised=True)
        store.create_answer(pending_a)
        store.create_answer(approved_a)
        results = store.search("connection pool")
        assert len(results) == 1
        answer_ids = [t["answer"].id for t in results[0]["answers"]]
        assert approved_a.id in answer_ids
        assert pending_a.id not in answer_ids

    def test_max_3_answers_per_question(self, store: SqliteStore) -> None:
        q = _make_question(title="max answers question test")
        store.create_question(q, [])
        for i in range(5):
            a = _make_answer(q.id, body=f"answer body {i}", supervised=True)
            store.create_answer(a)
        results = store.search("max answers question")
        assert len(results[0]["answers"]) <= 3

    def test_pinned_answer_first(self, store: SqliteStore) -> None:
        q = _make_question(title="pinned answer ordering check")
        store.create_question(q, [])
        a1 = _make_answer(q.id, body="first answer content", supervised=True)
        a2 = _make_answer(q.id, body="second answer content", supervised=True)
        store.create_answer(a1)
        store.create_answer(a2)
        store.pin_answer(q.id, a2.id)
        results = store.search("pinned answer ordering")
        assert results[0]["answers"][0]["answer"].id == a2.id

    def test_comment_counts_exclude_pending(self, store: SqliteStore) -> None:
        q = _make_question(title="comment count search query test")
        store.create_question(q, [])
        a = _make_answer(q.id, body="comment target answer", supervised=True)
        store.create_answer(a)
        pending_c = _make_comment(a.id)  # agent = pending
        approved_c = _make_comment(a.id, created_by_type="human", created_by="alice")
        store.create_comment(pending_c)
        store.create_comment(approved_c)
        results = store.search("comment count search query")
        answer_thread = results[0]["answers"][0]
        comment_ids = [c.id for c in answer_thread["comments"]]
        assert approved_c.id in comment_ids
        assert pending_c.id not in comment_ids


class TestGetQuestionThread:
    def test_returns_question_with_ranked_answers(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a1 = _make_answer(q.id, supervised=True)
        a2 = _make_answer(q.id, supervised=True)
        store.create_answer(a1)
        store.create_answer(a2)
        thread = store.get_question_thread(q.id)
        assert thread is not None
        assert thread["question"].id == q.id
        assert len(thread["answers"]) == 2

    def test_returns_none_for_missing_question(self, store: SqliteStore) -> None:
        assert store.get_question_thread("q_nonexistent") is None

    def test_includes_approved_comments(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        c = _make_comment(a.id, created_by_type="human", created_by="alice")
        store.create_comment(c)
        thread = store.get_question_thread(q.id)
        answer_thread = thread["answers"][0]
        assert any(comment.id == c.id for comment in answer_thread["comments"])


class TestApproveRejectContent:
    def test_approve_answer(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        assert store.approve_content(a.id) is True
        assert store.get_answer(a.id).status == "approved"

    def test_reject_answer(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        assert store.reject_content(a.id) is True
        assert store.get_answer(a.id).status == "rejected"

    def test_approve_already_approved_returns_false(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        store.approve_content(a.id)
        assert store.approve_content(a.id) is False

    def test_approve_comment(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        c = _make_comment(a.id)
        store.create_comment(c)
        assert store.approve_content(c.id) is True


class TestEditQuestionAnswer:
    def test_edit_question_updates_body(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        updated = store.edit_question(q.id, "new body content", "alice", "human")
        assert updated.body == "new body content"
        assert store.get_question(q.id).body == "new body content"

    def test_edit_question_records_history(self, store: SqliteStore) -> None:
        q = _make_question(body="original body")
        store.create_question(q, [])
        store.edit_question(q.id, "new body", "alice", "human")
        history = store.get_question_history(q.id)
        assert len(history) == 1
        assert history[0].previous_body == "original body"
        assert history[0].new_body == "new body"

    def test_edit_answer_updates_body(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        updated = store.edit_answer(a.id, "edited answer", "alice", "human")
        assert updated.body == "edited answer"

    def test_edit_answer_records_history(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, body="original answer body")
        store.create_answer(a)
        store.edit_answer(a.id, "new answer", "alice", "human")
        history = store.get_answer_history(a.id)
        assert len(history) == 1
        assert history[0].previous_body == "original answer body"


class TestPendingQueue:
    def test_returns_pending_answers_and_comments(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        c = _make_comment(a.id)
        store.create_comment(c)
        queue = store.pending_queue()
        assert any(x.id == a.id for x in queue["answers"])
        assert any(x.id == c.id for x in queue["comments"])

    def test_approved_items_excluded(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        queue = store.pending_queue()
        assert not any(x.id == a.id for x in queue["answers"])


class TestFindSimilarQuestions:
    def test_returns_similar_by_title(self, store: SqliteStore) -> None:
        q = _make_question(title="connection pool configuration best practices")
        store.create_question(q, ["databases"])
        similar = store.find_similar_questions("connection pool configuration", ["databases"])
        assert len(similar) >= 1
        assert similar[0]["question"].id == q.id

    def test_threshold_filters_low_similarity(self, store: SqliteStore) -> None:
        q = _make_question(title="completely unrelated topic xyz")
        store.create_question(q, [])
        # Search for something very different — should not match above threshold.
        similar = store.find_similar_questions("python decorators explained", [])
        assert not any(r["question"].id == q.id for r in similar)

    def test_returns_top_3(self, store: SqliteStore) -> None:
        for i in range(5):
            q = _make_question(title=f"connection pool question number {i}")
            store.create_question(q, ["databases"])
        similar = store.find_similar_questions("connection pool question", ["databases"])
        assert len(similar) <= 3


class TestGetOrCreateTag:
    def test_creates_new_tag(self, store: SqliteStore) -> None:
        tag = store.get_or_create_tag("python")
        assert tag.name == "python"
        assert tag.id.startswith("t_")

    def test_returns_existing_tag(self, store: SqliteStore) -> None:
        t1 = store.get_or_create_tag("python")
        t2 = store.get_or_create_tag("python")
        assert t1.id == t2.id


class TestMergeTags:
    def test_merge_repoints_question_tags(self, store: SqliteStore) -> None:
        q = _make_question()
        source = store.get_or_create_tag("py")
        target = store.get_or_create_tag("python")
        store.create_question(q, ["py"])
        store.merge_tags(source.id, target.id)
        tags = store._get_question_tag_names(q.id)
        assert "python" in tags
        assert "py" not in tags

    def test_merge_deletes_source_tag(self, store: SqliteStore, conn: sqlite3.Connection) -> None:
        source = store.get_or_create_tag("py")
        target = store.get_or_create_tag("python")
        store.merge_tags(source.id, target.id)
        row = conn.execute("SELECT id FROM tags WHERE id = ?", (source.id,)).fetchone()
        assert row is None


class TestPinAnswer:
    def test_pin_sets_pinned_answer_id(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        updated = store.pin_answer(q.id, a.id)
        assert updated.pinned_answer_id == a.id

    def test_unpin_clears_pinned_answer_id(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        store.pin_answer(q.id, a.id)
        updated = store.unpin_answer(q.id)
        assert updated.pinned_answer_id is None


class TestGetStatus:
    def test_status_empty_store(self, store: SqliteStore) -> None:
        status = store.get_status()
        assert status["total_questions"] == 0
        assert status["total_answers"] == 0
        assert status["total_tags"] == 0
        assert status["total_votes"] == 0
        assert status["unanswered"] == 0
        assert status["pending"] == 0

    def test_status_counts(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, ["python"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        store.cast_vote(_make_vote(a.id))
        status = store.get_status()
        assert status["total_questions"] == 1
        assert status["total_answers"] == 1
        assert status["total_tags"] == 1
        assert status["total_votes"] == 1
        assert status["unanswered"] == 0

    def test_unanswered_counts_correctly(self, store: SqliteStore) -> None:
        q1 = _make_question()
        q2 = _make_question(title="Unanswered question here")
        store.create_question(q1, [])
        store.create_question(q2, [])
        a = _make_answer(q1.id, supervised=True)
        store.create_answer(a)
        status = store.get_status()
        assert status["unanswered"] == 1

    def test_pending_count_includes_answers_and_comments(self, store: SqliteStore) -> None:
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)  # pending
        store.create_answer(a)
        c = _make_comment(a.id)  # pending
        store.create_comment(c)
        status = store.get_status()
        assert status["pending"] == 2


class TestUserManagement:
    def test_create_and_get_user(self, store: SqliteStore) -> None:
        store.create_user("alice", "hashed_pw")
        user = store.get_user("alice")
        assert user is not None
        assert user["username"] == "alice"
        assert user["password_hash"] == "hashed_pw"

    def test_get_nonexistent_user(self, store: SqliteStore) -> None:
        assert store.get_user("nobody") is None

    def test_duplicate_user_raises(self, store: SqliteStore) -> None:
        store.create_user("alice", "hash1")
        with pytest.raises(sqlite3.IntegrityError):
            store.create_user("alice", "hash2")
