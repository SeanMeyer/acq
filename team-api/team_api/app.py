"""ACQ team knowledge store API — agent-facing routes."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from starlette.exceptions import HTTPException as _StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope
from pydantic import BaseModel

from acq_shared.models import Answer, Comment, Question, Vote
from acq_shared.store import Store

from .auth import get_agent_identity, router as auth_router
from .deps import get_store
from .questions import router as questions_router
from .review import router as review_router
from .tags import router as tags_router


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class CreateQuestionRequest(BaseModel):
    id: str | None = None
    title: str
    body: str
    tags: list[str] = []
    context_language: str | None = None
    context_framework: str | None = None
    context_pattern: str | None = None
    force_create: bool = False


class CreateQuestionResponse(BaseModel):
    question: dict[str, Any]
    similar_questions: list[dict[str, Any]] = []


class CreateAnswerRequest(BaseModel):
    id: str | None = None
    body: str
    supervised: bool = False


class VoteRequest(BaseModel):
    target_id: str
    target_type: Literal["question", "answer"]
    value: Literal[1, -1]


class CommentRequest(BaseModel):
    parent_id: str
    parent_type: Literal["question", "answer"]
    body: str


# ------------------------------------------------------------------
# Lifespan / store
# ------------------------------------------------------------------

_store: Store | None = None


def _get_store() -> Store:
    if _store is None:
        raise RuntimeError("Store not initialised")
    return _store


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    global _store  # noqa: PLW0603
    jwt_secret = os.environ.get("ACQ_JWT_SECRET")
    if not jwt_secret:
        raise RuntimeError("ACQ_JWT_SECRET environment variable is required")

    # Postgres when DATABASE_URL is set, otherwise SQLite. DATABASE_URL is a
    # standard libpq connection string, e.g.
    #   postgresql://user:password@host:5432/acq?sslmode=require
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import psycopg2

        from acq_shared.postgres_store import PostgresStore

        # Passed to PostgresStore so it can re-open a dropped connection.
        def _connect():
            return psycopg2.connect(database_url)

        _store = PostgresStore(_connect(), connect=_connect)
    else:
        # Local dev / test path — SQLite
        from acq_shared.sqlite_store import SqliteStore

        db_path = Path(os.environ.get("ACQ_DB_PATH", "/data/team.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _store = SqliteStore(conn)

    app_instance.state.store = _store
    yield
    _store.close()


app = FastAPI(title="ACQ Team API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(questions_router)
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
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.get_status()


# ------------------------------------------------------------------
# Tags listing (agent-facing)
# ------------------------------------------------------------------


@app.get("/tags")
def list_tags(
    q: Annotated[str | None, Query()] = None,
    _agent: str = Depends(get_agent_identity),
    store: Store = Depends(get_store),
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
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    results = store.search(
        q, tags=tags, language=language, framework=framework, limit=limit
    )
    return [_serialise_thread(r) for r in results]


# ------------------------------------------------------------------
# Questions
# ------------------------------------------------------------------


@app.post("/questions", status_code=201)
def create_question(
    request: CreateQuestionRequest,
    agent: str = Depends(get_agent_identity),
    store: Store = Depends(get_store),
) -> CreateQuestionResponse:
    # Check for duplicates first (unless force_create)
    if not request.force_create:
        similar = store.find_similar_questions(request.title, request.tags)
        if similar:
            return CreateQuestionResponse(
                question={"title": request.title, "body": request.body},
                similar_questions=[
                    {
                        "question": s["question"].model_dump(mode="json"),
                        "similarity": s["similarity"],
                    }
                    for s in similar
                ],
            )
    kwargs: dict[str, Any] = {
        "title": request.title,
        "body": request.body,
        "created_by": agent,
        "created_by_type": "agent",
        "context_language": request.context_language,
        "context_framework": request.context_framework,
        "context_pattern": request.context_pattern,
    }
    if request.id is not None:
        kwargs["id"] = request.id
    q = Question(**kwargs)
    store.create_question(q, request.tags)
    return CreateQuestionResponse(question=q.model_dump(mode="json"))


@app.post("/questions/{question_id}/answers", status_code=201)
def create_answer(
    question_id: str,
    request: CreateAnswerRequest,
    agent: str = Depends(get_agent_identity),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    q = store.get_question(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    kwargs: dict[str, Any] = {
        "question_id": question_id,
        "body": request.body,
        "created_by": agent,
        "created_by_type": "agent",
        "supervised": request.supervised,
    }
    if request.id is not None:
        kwargs["id"] = request.id
    a = Answer(**kwargs)
    result = store.create_answer(a)
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Votes
# ------------------------------------------------------------------


@app.post("/vote")
def cast_vote(
    request: VoteRequest,
    agent: str = Depends(get_agent_identity),
    store: Store = Depends(get_store),
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
    store: Store = Depends(get_store),
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
# Export
# ------------------------------------------------------------------


@app.get("/export")
def export_data(
    since: str | None = None,
    _agent: str = Depends(get_agent_identity),
    store: Store = Depends(get_store),
) -> dict:
    return store.export_since(since=since)


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


# ------------------------------------------------------------------
# SPA static files (must be last — catch-all for UI routes)
# ------------------------------------------------------------------

_STATIC_DIR = Path(os.environ.get("ACQ_STATIC_DIR", "/app/static"))


class _SPAStaticFiles(StaticFiles):
    """Serve static files with SPA fallback (index.html for unknown paths)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except _StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if _STATIC_DIR.is_dir():
    app.mount("/", _SPAStaticFiles(directory=_STATIC_DIR, html=True), name="ui")


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
