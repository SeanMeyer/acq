"""Contract tests for Store protocol implementations.

Every class that satisfies the Store protocol must pass these tests.
Currently: SqliteStore. Later: PostgresStore.
"""

from __future__ import annotations

import os
import sqlite3

import pytest
from acq_shared.models import Answer, Comment, Question, Tag, Vote
from acq_shared.sqlite_store import SqliteStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    if request.param == "sqlite":
        conn = sqlite3.connect(":memory:")
        s = SqliteStore(conn)
        yield s
        s.close()
    else:
        dsn = os.environ.get("ACQ_TEST_PG_DSN")
        if dsn is None:
            pytest.skip("ACQ_TEST_PG_DSN not set")
        import psycopg2
        from acq_shared.postgres_store import PostgresStore

        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("DROP SCHEMA IF EXISTS dogpark CASCADE")
        conn.commit()
        cur.close()
        s = PostgresStore(conn)
        yield s
        cur = conn.cursor()
        cur.execute("DROP SCHEMA IF EXISTS dogpark CASCADE")
        conn.commit()
        cur.close()
        s.close()


def _make_question(**overrides) -> Question:
    defaults = dict(
        title="Why does webpack 5 fail?",
        body="Getting Module not found error for stream.",
        created_by="agent-1",
        created_by_type="agent",
        context_language="typescript",
        context_framework="nextjs",
    )
    defaults.update(overrides)
    return Question(**defaults)


def _make_answer(question_id: str, **overrides) -> Answer:
    defaults = dict(
        question_id=question_id,
        body="Add resolve.fallback in next.config.js.",
        created_by="agent-2",
        created_by_type="agent",
    )
    defaults.update(overrides)
    return Answer(**defaults)


# ===================================================================
# CRUD — Questions
# ===================================================================


class TestCreateQuestion:
    def test_returns_question(self, store):
        q = _make_question()
        result = store.create_question(q, ["webpack", "typescript"])
        assert result.id == q.id
        assert result.title == q.title

    def test_tags_created(self, store):
        q = _make_question()
        store.create_question(q, ["webpack", "typescript"])
        tags = store.list_tags()
        names = {t.name for t in tags}
        assert "webpack" in names
        assert "typescript" in names

    def test_get_question_after_create(self, store):
        q = _make_question()
        store.create_question(q, [])
        fetched = store.get_question(q.id)
        assert fetched is not None
        assert fetched.id == q.id
        assert fetched.body == q.body


class TestGetQuestion:
    def test_missing_returns_none(self, store):
        assert store.get_question("q_nonexistent") is None


class TestEditQuestion:
    def test_edit_updates_body(self, store):
        q = _make_question()
        store.create_question(q, [])
        updated = store.edit_question(q.id, "New body text", "editor", "human")
        assert updated is not None
        assert updated.body == "New body text"

    def test_edit_missing_returns_none(self, store):
        assert store.edit_question("q_none", "x", "e", "human") is None


# ===================================================================
# CRUD — Answers
# ===================================================================


class TestCreateAnswer:
    def test_returns_answer(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        result = store.create_answer(a)
        assert result.id == a.id

    def test_supervised_answer_auto_approved(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        result = store.create_answer(a)
        assert result.status == "approved"

    def test_unsupervised_answer_pending(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=False)
        result = store.create_answer(a)
        assert result.status == "pending"


class TestGetAnswer:
    def test_get_after_create(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        fetched = store.get_answer(a.id)
        assert fetched is not None
        assert fetched.body == a.body

    def test_missing_returns_none(self, store):
        assert store.get_answer("a_nonexistent") is None


class TestEditAnswer:
    def test_edit_updates_body(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        updated = store.edit_answer(a.id, "Updated answer body", "editor", "human")
        assert updated is not None
        assert updated.body == "Updated answer body"

    def test_edit_missing_returns_none(self, store):
        assert store.edit_answer("a_none", "x", "e", "human") is None


# ===================================================================
# Comments
# ===================================================================


class TestCreateComment:
    def test_returns_comment(self, store):
        q = _make_question()
        store.create_question(q, [])
        c = Comment(
            parent_id=q.id,
            parent_type="question",
            body="Good question!",
            created_by="human-1",
            created_by_type="human",
        )
        result = store.create_comment(c)
        assert result.id == c.id

    def test_human_comment_auto_approved(self, store):
        q = _make_question()
        store.create_question(q, [])
        c = Comment(
            parent_id=q.id,
            parent_type="question",
            body="Nice",
            created_by="human-1",
            created_by_type="human",
        )
        result = store.create_comment(c)
        assert result.status == "approved"


# ===================================================================
# Votes — with dedup
# ===================================================================


class TestCastVote:
    def test_upvote_returns_counts(self, store):
        q = _make_question()
        store.create_question(q, [])
        v = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-1",
            voter_type="agent",
            value=1,
        )
        result = store.cast_vote(v)
        assert result.get("agent_upvotes") == 1

    def test_duplicate_vote_rejected(self, store):
        q = _make_question()
        store.create_question(q, [])
        v1 = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-1",
            voter_type="agent",
            value=1,
        )
        store.cast_vote(v1)
        v2 = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-1",
            voter_type="agent",
            value=1,
        )
        result = store.cast_vote(v2)
        assert result.get("error") == "duplicate_vote"

    def test_different_voters_both_count(self, store):
        q = _make_question()
        store.create_question(q, [])
        v1 = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-1",
            voter_type="agent",
            value=1,
        )
        v2 = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-2",
            voter_type="agent",
            value=1,
        )
        store.cast_vote(v1)
        result = store.cast_vote(v2)
        assert result.get("agent_upvotes") == 2

    def test_vote_updates_denormalized_counts(self, store):
        q = _make_question()
        store.create_question(q, [])
        v = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="human-1",
            voter_type="human",
            value=1,
        )
        store.cast_vote(v)
        fetched = store.get_question(q.id)
        assert fetched is not None
        assert fetched.human_upvotes == 1

    def test_human_downvote_accepted(self, store):
        """Human downvotes are allowed at the store level (agent restriction is MCP-only)."""
        q = _make_question()
        store.create_question(q, [])
        v = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="human-1",
            voter_type="human",
            value=-1,
        )
        result = store.cast_vote(v)
        assert result.get("human_downvotes") == 1


# ===================================================================
# Moderation — approve / reject
# ===================================================================


class TestModeration:
    def test_approve_pending_answer(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=False)
        store.create_answer(a)
        assert store.approve_content(a.id) is True
        fetched = store.get_answer(a.id)
        assert fetched.status == "approved"

    def test_approve_non_pending_returns_false(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)  # auto-approved
        assert store.approve_content(a.id) is False

    def test_reject_pending_answer(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=False)
        store.create_answer(a)
        assert store.reject_content(a.id) is True
        fetched = store.get_answer(a.id)
        assert fetched.status == "rejected"

    def test_approve_missing_returns_false(self, store):
        assert store.approve_content("nonexistent") is False

    def test_reject_missing_returns_false(self, store):
        assert store.reject_content("nonexistent") is False

    def test_pending_queue_lists_pending(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=False)
        store.create_answer(a)
        queue = store.pending_queue()
        assert len(queue["answers"]) == 1
        assert queue["answers"][0].id == a.id

    def test_approved_not_in_pending_queue(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        queue = store.pending_queue()
        assert len(queue["answers"]) == 0


# ===================================================================
# Edit history
# ===================================================================


class TestEditHistory:
    def test_question_edit_creates_history(self, store):
        q = _make_question()
        store.create_question(q, [])
        store.edit_question(q.id, "Revised body", "editor", "human")
        history = store.get_question_history(q.id)
        assert len(history) == 1
        assert history[0].previous_body == q.body
        assert history[0].new_body == "Revised body"

    def test_answer_edit_creates_history(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id)
        store.create_answer(a)
        store.edit_answer(a.id, "Revised answer", "editor", "human")
        history = store.get_answer_history(a.id)
        assert len(history) == 1
        assert history[0].previous_body == a.body
        assert history[0].new_body == "Revised answer"

    def test_multiple_edits_accumulate(self, store):
        q = _make_question()
        store.create_question(q, [])
        store.edit_question(q.id, "Edit 1", "e1", "human")
        store.edit_question(q.id, "Edit 2", "e2", "agent")
        history = store.get_question_history(q.id)
        assert len(history) == 2


# ===================================================================
# Tags — get_or_create, list, merge
# ===================================================================


class TestTags:
    def test_get_or_create_returns_tag(self, store):
        tag = store.get_or_create_tag("webpack")
        assert tag.name == "webpack"
        assert tag.id.startswith("t_")

    def test_get_or_create_idempotent(self, store):
        t1 = store.get_or_create_tag("webpack")
        t2 = store.get_or_create_tag("webpack")
        assert t1.id == t2.id

    def test_list_tags_empty(self, store):
        assert store.list_tags() == []

    def test_list_tags_returns_all(self, store):
        store.get_or_create_tag("webpack")
        store.get_or_create_tag("typescript")
        tags = store.list_tags()
        assert len(tags) == 2

    def test_list_tags_filter(self, store):
        store.get_or_create_tag("webpack")
        store.get_or_create_tag("typescript")
        tags = store.list_tags(q="web")
        assert len(tags) == 1
        assert tags[0].name == "webpack"

    def test_merge_tags(self, store):
        q = _make_question()
        store.create_question(q, ["webpack", "wp"])
        tags_before = {t.name: t for t in store.list_tags()}
        store.merge_tags(tags_before["wp"].id, tags_before["webpack"].id)
        tags_after = store.list_tags()
        names = {t.name for t in tags_after}
        assert "wp" not in names
        assert "webpack" in names

    def test_tag_slugification(self, store):
        tag = store.get_or_create_tag("GitHub Actions")
        assert tag.name == "github-actions"


# ===================================================================
# Search — FTS5
# ===================================================================


class TestSearch:
    def test_search_returns_matching_question(self, store):
        q = _make_question(title="webpack stream polyfill error")
        store.create_question(q, ["webpack"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        results = store.search("webpack stream")
        assert len(results) >= 1

    def test_search_no_results(self, store):
        results = store.search("nonexistent query xyz")
        assert results == []

    def test_search_respects_limit(self, store):
        for i in range(5):
            q = _make_question(title=f"webpack question {i}")
            store.create_question(q, ["webpack"])
            a = _make_answer(q.id, supervised=True)
            store.create_answer(a)
        results = store.search("webpack", limit=2)
        assert len(results) <= 2

    def test_search_tag_filter_boosts(self, store):
        q1 = _make_question(title="webpack bundler issue")
        store.create_question(q1, ["webpack"])
        a1 = _make_answer(q1.id, supervised=True)
        store.create_answer(a1)
        q2 = _make_question(title="webpack config setup")
        store.create_question(q2, ["webpack", "config"])
        a2 = _make_answer(q2.id, supervised=True)
        store.create_answer(a2)
        # Searching with tag=["config"] should still return results
        results = store.search("webpack", tags=["config"])
        assert len(results) >= 1

    def test_search_finds_question_by_tag_keyword(self, store):
        """A search for a tag name should find questions even if the tag
        doesn't appear in the title or body."""
        q = _make_question(title="Build fails on CI", body="The pipeline errors out.")
        store.create_question(q, ["howler", "ci-pipeline"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        results = store.search("howler")
        assert len(results) >= 1
        assert results[0]["question"].id == q.id

    def test_search_hyphenated_terms(self, store):
        """Hyphenated terms like 'version-updater' must not break FTS."""
        q = _make_question(title="How to run version-updater", body="Use the CLI.")
        store.create_question(q, ["version-updater"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        results = store.search("version-updater control renovate")
        assert len(results) >= 1
        assert results[0]["question"].id == q.id

    def test_search_bad_fts_query_returns_empty(self, store):
        """FTS5 syntax errors should not crash, just return []."""
        results = store.search("AND OR NOT")
        assert results == []

    def test_search_zero_votes_returns_nonzero_score(self, store):
        """New content with 0 votes should surface in search results."""
        q = _make_question(title="authenticate with OIDC tokens")
        store.create_question(q, ["auth"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        results = store.search("authenticate OIDC")
        assert len(results) >= 1
        assert results[0]["question"].id == q.id

    def test_search_voted_ranks_above_unvoted(self, store):
        """Voted content should rank higher than identical unvoted content."""
        q_unvoted = _make_question(title="webpack polyfill stream fix")
        store.create_question(q_unvoted, ["webpack"])
        a_unvoted = _make_answer(q_unvoted.id, supervised=True)
        store.create_answer(a_unvoted)

        q_voted = _make_question(title="webpack polyfill stream fix")
        store.create_question(q_voted, ["webpack"])
        a_voted = _make_answer(q_voted.id, supervised=True)
        store.create_answer(a_voted)
        # Give the voted question some upvotes
        store.cast_vote(
            Vote(
                target_id=q_voted.id,
                target_type="question",
                voter_id="agent-1",
                voter_type="agent",
                value=1,
            )
        )
        store.cast_vote(
            Vote(
                target_id=a_voted.id,
                target_type="answer",
                voter_id="agent-1",
                voter_type="agent",
                value=1,
            )
        )

        results = store.search("webpack polyfill stream")
        assert len(results) >= 2
        assert results[0]["question"].id == q_voted.id


# ===================================================================
# find_similar_questions
# ===================================================================


class TestFindSimilar:
    def test_finds_similar(self, store):
        q = _make_question(title="webpack stream polyfill")
        store.create_question(q, ["webpack"])
        results = store.find_similar_questions("webpack polyfill", ["webpack"])
        assert len(results) >= 1
        assert results[0]["question"].id == q.id

    def test_no_similar_returns_empty(self, store):
        results = store.find_similar_questions("something totally different", [])
        assert results == []


# ===================================================================
# export_since / bulk_upsert
# ===================================================================


class TestExportSince:
    def test_export_empty(self, store):
        data = store.export_since()
        assert data["questions"] == []
        assert data["answers"] == []

    def test_export_returns_all_content(self, store):
        q = _make_question()
        store.create_question(q, ["webpack"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        data = store.export_since()
        assert len(data["questions"]) == 1
        assert len(data["answers"]) == 1
        assert len(data["tags"]) == 1

    def test_export_since_filters_by_date(self, store):
        q = _make_question()
        store.create_question(q, [])
        # Export with a future date should return nothing
        data = store.export_since(since="2099-01-01T00:00:00+00:00")
        assert data["questions"] == []


class TestBulkUpsert:
    def test_import_into_empty_store(self, store):
        """Bulk upsert into an empty store should insert everything."""
        q = _make_question()
        a = _make_answer(q.id)
        tag = Tag(name="webpack")
        data = {
            "questions": [q.model_dump(mode="json")],
            "answers": [a.model_dump(mode="json")],
            "tags": [tag.model_dump(mode="json")],
            "question_tags": [{"question_id": q.id, "tag_id": tag.id}],
            "votes": [],
            "comments": [],
        }
        count = store.bulk_upsert(data)
        assert count > 0
        fetched = store.get_question(q.id)
        assert fetched is not None
        assert fetched.title == q.title

    def test_upsert_is_idempotent(self, store):
        """Bulk upserting the same data twice should not error or duplicate."""
        q = _make_question()
        data = {
            "questions": [q.model_dump(mode="json")],
            "answers": [],
            "tags": [],
            "question_tags": [],
            "votes": [],
            "comments": [],
        }
        store.bulk_upsert(data)
        store.bulk_upsert(data)
        status = store.get_status()
        assert status["total_questions"] == 1


# ===================================================================
# Pin / Unpin
# ===================================================================


class TestPinUnpin:
    def test_pin_answer(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        result = store.pin_answer(q.id, a.id)
        assert result is not None
        assert result.pinned_answer_id == a.id

    def test_unpin_answer(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        store.pin_answer(q.id, a.id)
        result = store.unpin_answer(q.id)
        assert result is not None
        assert result.pinned_answer_id is None

    def test_pin_missing_question_returns_none(self, store):
        assert store.pin_answer("q_none", "a_none") is None

    def test_unpin_missing_question_returns_none(self, store):
        assert store.unpin_answer("q_none") is None


# ===================================================================
# Status counts
# ===================================================================


class TestGetStatus:
    def test_empty_status(self, store):
        status = store.get_status()
        assert status["total_questions"] == 0
        assert status["total_answers"] == 0
        assert status["total_tags"] == 0
        assert status["total_votes"] == 0
        assert status["unanswered"] == 0
        assert status["pending"] == 0

    def test_status_counts(self, store):
        q = _make_question()
        store.create_question(q, ["webpack"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        v = Vote(
            target_id=q.id,
            target_type="question",
            voter_id="agent-1",
            voter_type="agent",
            value=1,
        )
        store.cast_vote(v)
        status = store.get_status()
        assert status["total_questions"] == 1
        assert status["total_answers"] == 1
        assert status["total_tags"] == 1
        assert status["total_votes"] == 1
        assert status["unanswered"] == 0

    def test_unanswered_count(self, store):
        q = _make_question()
        store.create_question(q, [])
        status = store.get_status()
        assert status["unanswered"] == 1


# ===================================================================
# User management
# ===================================================================


class TestUserManagement:
    def test_create_and_get_user(self, store):
        store.create_user("alice", "hash123")
        user = store.get_user("alice")
        assert user is not None
        assert user["username"] == "alice"
        assert user["password_hash"] == "hash123"

    def test_get_missing_user(self, store):
        assert store.get_user("nobody") is None

    def test_duplicate_user_raises(self, store):
        store.create_user("alice", "hash1")
        with pytest.raises(Exception):
            store.create_user("alice", "hash2")


# ===================================================================
# Question thread
# ===================================================================


class TestGetQuestionThread:
    def test_thread_includes_answers_and_comments(self, store):
        q = _make_question()
        store.create_question(q, ["webpack"])
        a = _make_answer(q.id, supervised=True)
        store.create_answer(a)
        c = Comment(
            parent_id=q.id,
            parent_type="question",
            body="Good question!",
            created_by="human-1",
            created_by_type="human",
        )
        store.create_comment(c)
        thread = store.get_question_thread(q.id)
        assert thread is not None
        assert thread["question"].id == q.id
        assert len(thread["answers"]) == 1
        assert len(thread["comments"]) == 1

    def test_thread_missing_returns_none(self, store):
        assert store.get_question_thread("q_nonexistent") is None

    def test_thread_default_excludes_pending(self, store):
        q = _make_question()
        store.create_question(q, [])
        a_pending = _make_answer(q.id, supervised=False)
        store.create_answer(a_pending)
        a_approved = _make_answer(q.id, supervised=True)
        store.create_answer(a_approved)
        thread = store.get_question_thread(q.id)
        assert len(thread["answers"]) == 1
        assert thread["answers"][0]["answer"].id == a_approved.id

    def test_thread_include_pending(self, store):
        q = _make_question()
        store.create_question(q, [])
        a_pending = _make_answer(q.id, supervised=False)
        store.create_answer(a_pending)
        a_approved = _make_answer(q.id, supervised=True)
        store.create_answer(a_approved)
        thread = store.get_question_thread(q.id, include_pending=True)
        assert len(thread["answers"]) == 2
        # Approved answers come first, then pending
        assert thread["answers"][0]["answer"].id == a_approved.id
        assert thread["answers"][0]["answer"].status == "approved"
        assert thread["answers"][1]["answer"].id == a_pending.id
        assert thread["answers"][1]["answer"].status == "pending"

    def test_thread_excludes_rejected_answers(self, store):
        q = _make_question()
        store.create_question(q, [])
        a = _make_answer(q.id, supervised=False)
        store.create_answer(a)
        store.reject_content(a.id)
        thread = store.get_question_thread(q.id, include_pending=True)
        assert len(thread["answers"]) == 0


# ===================================================================
# List Questions
# ===================================================================


class TestListQuestions:
    def test_list_all(self, store):
        q1 = _make_question(title="First question")
        q2 = _make_question(title="Second question")
        store.create_question(q1, ["python"])
        store.create_question(q2, ["go"])
        items, total = store.list_questions()
        assert total == 2
        assert len(items) == 2
        # Ordered by created_at DESC — q2 was created second
        assert items[0]["question"]["id"] == q2.id
        assert items[1]["question"]["id"] == q1.id

    def test_list_includes_tags(self, store):
        q = _make_question()
        store.create_question(q, ["python", "django"])
        items, total = store.list_questions()
        assert total == 1
        tag_names = {t["name"] for t in items[0]["tags"]}
        assert tag_names == {"python", "django"}

    def test_filter_by_status(self, store):
        q_open = _make_question(title="Open question", status="open")
        q_resolved = _make_question(title="Resolved question", status="resolved")
        store.create_question(q_open, [])
        store.create_question(q_resolved, [])
        items, total = store.list_questions(status="open")
        assert total == 1
        assert items[0]["question"]["id"] == q_open.id

    def test_filter_by_tag(self, store):
        q1 = _make_question(title="Python question")
        q2 = _make_question(title="Go question")
        store.create_question(q1, ["python"])
        store.create_question(q2, ["go"])
        items, total = store.list_questions(tag="python")
        assert total == 1
        assert items[0]["question"]["id"] == q1.id

    def test_pagination(self, store):
        questions = []
        for i in range(5):
            q = _make_question(title=f"Question {i}")
            store.create_question(q, [])
            questions.append(q)
        items, total = store.list_questions(limit=2, offset=0)
        assert total == 5
        assert len(items) == 2
        items2, total2 = store.list_questions(limit=2, offset=2)
        assert total2 == 5
        assert len(items2) == 2
        # No overlap
        ids1 = {i["question"]["id"] for i in items}
        ids2 = {i["question"]["id"] for i in items2}
        assert ids1.isdisjoint(ids2)

    def test_empty_results(self, store):
        items, total = store.list_questions()
        assert total == 0
        assert items == []

    def test_filter_by_status_and_tag(self, store):
        q1 = _make_question(title="Open Python", status="open")
        q2 = _make_question(title="Resolved Python", status="resolved")
        q3 = _make_question(title="Open Go", status="open")
        store.create_question(q1, ["python"])
        store.create_question(q2, ["python"])
        store.create_question(q3, ["go"])
        items, total = store.list_questions(status="open", tag="python")
        assert total == 1
        assert items[0]["question"]["id"] == q1.id
