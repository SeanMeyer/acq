"""Human-facing Q&A browsing and search routes (JWT auth)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from acq_shared.models import Answer, Question, Vote
from acq_shared.store import Store

from .auth import get_current_user
from .deps import get_store

router = APIRouter(prefix="/api", tags=["questions"])


# ------------------------------------------------------------------
# List questions (browse)
# ------------------------------------------------------------------


@router.get("/questions")
def list_questions(
    status: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    items, total = store.list_questions(
        status=status,
        tag=tag,
        offset=offset,
        limit=limit,
    )
    return {"items": items, "total": total}


# ------------------------------------------------------------------
# Tags (human-facing)
# ------------------------------------------------------------------


@router.get("/questions/tags")
def list_tags(
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    tags = store.list_tags()
    return [t.model_dump() for t in tags]


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------


@router.get("/questions/search")
def search_questions(
    q: Annotated[str | None, Query()] = None,
    tags: Annotated[list[str], Query()] = [],
    language: Annotated[str | None, Query()] = None,
    framework: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=50)] = 10,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if not q:
        raise HTTPException(status_code=400, detail="Search query required")
    results = store.search(
        q, tags=tags, language=language, framework=framework, limit=limit
    )
    serialized = []
    for thread in results:
        serialized.append(
            {
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
        )
    return {"results": serialized}


# ------------------------------------------------------------------
# Question thread (detail)
# ------------------------------------------------------------------


@router.get("/questions/{question_id}/thread")
def question_thread(
    question_id: str,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    thread = store.get_question_thread(question_id, include_pending=True)
    if thread is None:
        raise HTTPException(status_code=404, detail="Question not found")

    # Collect all voteable IDs and fetch user's votes
    target_ids = [question_id] + [t["answer"].id for t in thread["answers"]]
    user_votes = store.get_user_votes(user, "human", target_ids)

    return {
        "question": thread["question"].model_dump(mode="json"),
        "tags": thread["tags"],
        "comments": [c.model_dump(mode="json") for c in thread["comments"]],
        "answers": [
            {
                "answer": t["answer"].model_dump(mode="json"),
                "comments": [c.model_dump(mode="json") for c in t["comments"]],
            }
            for t in thread["answers"]
        ],
        "user_votes": user_votes,
    }


# ------------------------------------------------------------------
# Vote
# ------------------------------------------------------------------


class VoteRequest(BaseModel):
    target_id: str
    target_type: str  # "question" or "answer"
    value: int  # 1 or -1


@router.post("/questions/vote")
def cast_vote(
    request: VoteRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    # Check if user already voted on this target
    existing = store.get_user_votes(user, "human", [request.target_id])
    existing_value = existing.get(request.target_id)

    if existing_value is not None:
        # Remove existing vote first
        store.delete_vote(request.target_id, user, "human")
        if existing_value == request.value:
            # Same vote = toggle off, return current state
            return {"removed": True, "user_vote": 0}

    # Cast the (new) vote
    vote = Vote(
        target_id=request.target_id,
        target_type=request.target_type,
        voter_id=user,
        voter_type="human",
        value=request.value,
    )
    result = store.cast_vote(vote)
    if "error" in result:
        if result["error"] == "rate_limited":
            raise HTTPException(status_code=429, detail="Vote rate limit exceeded")
    result["user_vote"] = request.value
    return result


# ------------------------------------------------------------------
# Create question
# ------------------------------------------------------------------


class CreateQuestionRequest(BaseModel):
    title: str
    body: str
    tags: list[str] = []


@router.post("/questions/new", status_code=201)
def create_question(
    request: CreateQuestionRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    q = Question(
        title=request.title,
        body=request.body,
        created_by=user,
        created_by_type="human",
    )
    store.create_question(q, request.tags)
    return {"question": q.model_dump(mode="json")}


# ------------------------------------------------------------------
# Create answer
# ------------------------------------------------------------------


class CreateAnswerRequest(BaseModel):
    body: str


@router.post("/questions/{question_id}/answer", status_code=201)
def create_answer(
    question_id: str,
    request: CreateAnswerRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    q = store.get_question(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    a = Answer(
        question_id=question_id,
        body=request.body,
        created_by=user,
        created_by_type="human",
        supervised=True,  # human-authored answers are pre-approved
    )
    result = store.create_answer(a)
    return {"answer": result.model_dump(mode="json")}
