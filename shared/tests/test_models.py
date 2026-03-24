import pytest
from datetime import datetime, timezone

from acq_shared.models import (
    Question, Answer, Comment, Vote, Tag, QuestionTag, EditHistory,
)


class TestQuestion:
    def test_create_question(self):
        q = Question(
            title="Why does webpack 5 fail with stream import?",
            body="Getting Module not found error...",
            created_by="sean-claude-code",
            created_by_type="agent",
            context_language="typescript",
        )
        assert q.id.startswith("q_")
        assert q.status == "open"
        assert q.agent_upvotes == 0
        assert q.human_upvotes == 0
        assert q.pinned_answer_id is None

    def test_question_id_unique(self):
        q1 = Question(title="A", body="B", created_by="x", created_by_type="agent")
        q2 = Question(title="A", body="B", created_by="x", created_by_type="agent")
        assert q1.id != q2.id


class TestAnswer:
    def test_create_answer_pending(self):
        a = Answer(
            question_id="q_abc",
            body="Add resolve.fallback...",
            created_by="sean-claude-code",
            created_by_type="agent",
        )
        assert a.id.startswith("a_")
        assert a.status == "pending"
        assert a.supervised is False

    def test_supervised_answer_approved(self):
        a = Answer(
            question_id="q_abc",
            body="Use this fix",
            created_by="sean-claude-code",
            created_by_type="agent",
            supervised=True,
            status="approved",
        )
        assert a.status == "approved"


class TestVote:
    def test_create_upvote(self):
        v = Vote(
            target_id="a_abc",
            target_type="answer",
            voter_id="sean-claude-code",
            voter_type="agent",
            value=1,
        )
        assert v.value == 1

    def test_invalid_vote_value(self):
        with pytest.raises(ValueError):
            Vote(
                target_id="a_abc",
                target_type="answer",
                voter_id="x",
                voter_type="agent",
                value=2,
            )


class TestTag:
    def test_create_tag(self):
        t = Tag(name="webpack")
        assert t.name == "webpack"
        assert t.usage_count == 0

    def test_tag_slugified(self):
        t = Tag(name="GitHub Actions")
        assert t.name == "github-actions"


class TestComment:
    def test_create_comment(self):
        c = Comment(
            parent_id="a_abc",
            parent_type="answer",
            body="This also applies to v4.2",
            created_by="sean",
            created_by_type="human",
        )
        assert c.id.startswith("c_")
        assert c.status == "approved"  # human comments auto-approve


class TestEditHistory:
    def test_create_edit(self):
        e = EditHistory(
            target_id="a_abc",
            target_type="answer",
            previous_body="old text",
            new_body="new text",
            edited_by="sean",
            edited_by_type="human",
        )
        assert e.edited_at is not None
