"""ACQ team knowledge store API — agent-facing routes."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from acq_shared.models import Answer, Comment, Question, Vote

from .auth import get_agent_identity, router as auth_router
from .deps import get_store
from .review import router as review_router
from .store import TeamStore
from .tags import router as tags_router


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------

class CreateQuestionRequest(BaseModel):
    title: str
    body: str
    created_by: str
    created_by_type: str = "agent"
    tags: list[str] = []
    context_language: str | None = None
    context_framework: str | None = None
    context_pattern: str | None = None


class CreateQuestionResponse(BaseModel):
    question: dict[str, Any]
    similar_questions: list[dict[str, Any]] = []


class CreateAnswerRequest(BaseModel):
    body: str
    supervised: bool = False


class VoteRequest(BaseModel):
    target_id: str
    target_type: str
    value: int  # 1 or -1


class CommentRequest(BaseModel):
    parent_id: str
    parent_type: str
    body: str


# ------------------------------------------------------------------
# Lifespan / store
# ------------------------------------------------------------------

_store: TeamStore | None = None


def _get_store() -> TeamStore:
    if _store is None:
        raise RuntimeError("Store not initialised")
    return _store


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    global _store  # noqa: PLW0603
    jwt_secret = os.environ.get("ACQ_JWT_SECRET")
    if not jwt_secret:
        raise RuntimeError("ACQ_JWT_SECRET environment variable is required")
    db_path = Path(os.environ.get("ACQ_DB_PATH", "/data/team.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _store = TeamStore(conn)
    app_instance.state.store = _store
    yield
    _store.close()


app = FastAPI(title="ACQ Team API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(review_router)
app.include_router(tags_router)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ------------------------------------------------------------------
# Status (agent-facing, API key auth)
# ------------------------------------------------------------------

@app.get("/status")
def status(
    _agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    return store.get_status()


# ------------------------------------------------------------------
# Tags listing (agent-facing)
# ------------------------------------------------------------------

@app.get("/tags")
def list_tags(
    q: Annotated[str | None, Query()] = None,
    _agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> list[dict[str, Any]]:
    tags = store.list_tags(q=q)
    return [t.model_dump() for t in tags]


# ------------------------------------------------------------------
# Search (agent-facing)
# ------------------------------------------------------------------

@app.get("/search")
def search(
    q: Annotated[str, Query()],
    tags: Annotated[list[str], Query()] = [],
    language: Annotated[str | None, Query()] = None,
    framework: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0)] = 10,
    _agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> list[dict[str, Any]]:
    results = store.search(q, tags=tags, language=language, framework=framework, limit=limit)
    return [_serialise_thread(r) for r in results]


# ------------------------------------------------------------------
# Questions
# ------------------------------------------------------------------

@app.post("/questions", status_code=201)
def create_question(
    request: CreateQuestionRequest,
    agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> CreateQuestionResponse:
    q = Question(
        title=request.title,
        body=request.body,
        created_by=request.created_by or agent,
        created_by_type=request.created_by_type,
        context_language=request.context_language,
        context_framework=request.context_framework,
        context_pattern=request.context_pattern,
    )
    similar = store.find_similar_questions(request.title, request.tags)
    if similar:
        return CreateQuestionResponse(
            question=q.model_dump(mode="json"),
            similar_questions=[
                {
                    "question": s["question"].model_dump(mode="json"),
                    "similarity": s["similarity"],
                }
                for s in similar
            ],
        )
    store.create_question(q, request.tags)
    return CreateQuestionResponse(question=q.model_dump(mode="json"))


@app.post("/questions/{question_id}/answers", status_code=201)
def create_answer(
    question_id: str,
    request: CreateAnswerRequest,
    agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    q = store.get_question(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    a = Answer(
        question_id=question_id,
        body=request.body,
        created_by=agent,
        created_by_type="agent",
        supervised=request.supervised,
    )
    result = store.create_answer(a)
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Votes
# ------------------------------------------------------------------

@app.post("/vote")
def cast_vote(
    request: VoteRequest,
    agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    vote = Vote(
        target_id=request.target_id,
        target_type=request.target_type,
        voter_id=agent,
        voter_type="agent",
        value=request.value,
    )
    result = store.cast_vote(vote)
    if "error" in result:
        if result["error"] == "duplicate_vote":
            raise HTTPException(status_code=409, detail="Duplicate vote")
        if result["error"] == "rate_limited":
            raise HTTPException(status_code=429, detail="Vote rate limit exceeded")
    return result


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------

@app.post("/comments", status_code=201)
def create_comment(
    request: CommentRequest,
    agent: str = Depends(get_agent_identity),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    c = Comment(
        parent_id=request.parent_id,
        parent_type=request.parent_type,
        body=request.body,
        created_by=agent,
        created_by_type="agent",
    )
    result = store.create_comment(c)
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Reflect (stub)
# ------------------------------------------------------------------

@app.post("/reflect")
def reflect(
    _agent: str = Depends(get_agent_identity),
) -> dict[str, str]:
    return {"message": "Reflection noted"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _serialise_thread(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": thread["question"].model_dump(mode="json"),
        "comments": [c.model_dump(mode="json") for c in thread["comments"]],
        "answers": [
            {
                "answer": t["answer"].model_dump(mode="json"),
                "comments": [c.model_dump(mode="json") for c in t["comments"]],
            }
            for t in thread["answers"]
        ],
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8742)
