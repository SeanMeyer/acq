from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class Question(BaseModel):
    """A question, with a review lifecycle mirroring the one on Answer.

    Agent-authored questions start at "pending" and are invisible to every
    read path until a human approves them. The promotion of human-authored and
    supervised questions to "open" deliberately lives in the store's
    create_question, not in a model_post_init hook: model_post_init re-runs on
    every model_validate_json, so promoting there would resurrect a rejected
    question on every single read.
    """

    id: str = Field(default_factory=lambda: _make_id("q_"))
    title: str
    body: str
    status: Literal["pending", "open", "resolved", "deleted"] = "pending"
    created_by: str
    created_by_type: Literal["agent", "human"]
    supervised: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    pinned_answer_id: str | None = None
    agent_upvotes: int = 0
    agent_downvotes: int = 0
    human_upvotes: int = 0
    human_downvotes: int = 0
    context_language: str | None = None
    context_framework: str | None = None
    context_pattern: str | None = None


class Answer(BaseModel):
    id: str = Field(default_factory=lambda: _make_id("a_"))
    question_id: str
    body: str
    created_by: str
    created_by_type: Literal["agent", "human"]
    supervised: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    status: Literal["pending", "approved", "rejected"] = "pending"
    agent_upvotes: int = 0
    agent_downvotes: int = 0
    human_upvotes: int = 0
    human_downvotes: int = 0


class Comment(BaseModel):
    id: str = Field(default_factory=lambda: _make_id("c_"))
    parent_id: str
    parent_type: Literal["question", "answer"]
    body: str
    created_by: str
    created_by_type: Literal["agent", "human"]
    supervised: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    status: Literal["pending", "approved", "rejected"] = "pending"

    def model_post_init(self, _context):
        # Human comments skip the review queue. This only promotes a comment
        # still sitting at the default status: model_post_init also runs on
        # every model_validate_json, so promoting unconditionally would
        # resurrect a human comment that had since been rejected.
        if self.created_by_type == "human" and self.status == "pending":
            object.__setattr__(self, "status", "approved")


class Vote(BaseModel):
    id: str = Field(default_factory=lambda: _make_id("v_"))
    target_id: str
    target_type: Literal["question", "answer"]
    voter_id: str
    voter_type: Literal["agent", "human"]
    value: Literal[1, -1]
    created_at: datetime = Field(default_factory=_utcnow)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


class Tag(BaseModel):
    id: str = Field(default_factory=lambda: _make_id("t_"))
    name: str
    description: str | None = None
    usage_count: int = 0

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return _slugify(v)


class QuestionTag(BaseModel):
    question_id: str
    tag_id: str


class EditHistory(BaseModel):
    id: str = Field(default_factory=lambda: _make_id("eh_"))
    target_id: str
    target_type: Literal["question", "question_title", "answer", "comment"]
    previous_body: str
    new_body: str
    edited_by: str
    edited_by_type: Literal["agent", "human"]
    edited_at: datetime = Field(default_factory=_utcnow)
