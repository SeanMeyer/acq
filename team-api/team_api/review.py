"""Human-facing review and editorial routes (JWT auth)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .deps import get_store
from .store import TeamStore

router = APIRouter(tags=["review"])


# ------------------------------------------------------------------
# Pending queue
# ------------------------------------------------------------------

@router.get("/review/queue")
def review_queue(
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    queue = store.pending_queue()
    return {
        "answers": [a.model_dump(mode="json") for a in queue["answers"]],
        "comments": [c.model_dump(mode="json") for c in queue["comments"]],
    }


# ------------------------------------------------------------------
# Approve / reject
# ------------------------------------------------------------------

@router.post("/review/{content_id}/approve")
def approve_content(
    content_id: str,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, str]:
    result = store.approve_content(content_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Content already reviewed")
    return {"id": content_id, "status": "approved"}


@router.post("/review/{content_id}/reject")
def reject_content(
    content_id: str,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, str]:
    result = store.reject_content(content_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Content already reviewed")
    return {"id": content_id, "status": "rejected"}


# ------------------------------------------------------------------
# Stats dashboard
# ------------------------------------------------------------------

@router.get("/review/stats")
def review_stats(
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    status = store.get_status()
    tag_rows = store.list_tags()
    return {
        "counts": {
            "total_questions": status["total_questions"],
            "total_answers": status["total_answers"],
            "pending": status["pending"],
            "unanswered": status["unanswered"],
        },
        "tags": [t.model_dump() for t in tag_rows],
        "total_votes": status["total_votes"],
    }


# ------------------------------------------------------------------
# Edit question / answer
# ------------------------------------------------------------------

class EditBodyRequest(BaseModel):
    body: str


@router.put("/questions/{question_id}")
def edit_question(
    question_id: str,
    request: EditBodyRequest,
    user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    result = store.edit_question(question_id, request.body, user, "human")
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return result.model_dump(mode="json")


@router.put("/answers/{answer_id}")
def edit_answer(
    answer_id: str,
    request: EditBodyRequest,
    user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    result = store.edit_answer(answer_id, request.body, user, "human")
    if result is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Pin / unpin answer
# ------------------------------------------------------------------

class PinRequest(BaseModel):
    answer_id: str


@router.put("/questions/{question_id}/pin")
def pin_answer(
    question_id: str,
    request: PinRequest,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    result = store.pin_answer(question_id, request.answer_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return result.model_dump(mode="json")


@router.delete("/questions/{question_id}/pin")
def unpin_answer(
    question_id: str,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    result = store.unpin_answer(question_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Edit history
# ------------------------------------------------------------------

@router.get("/questions/{question_id}/history")
def question_history(
    question_id: str,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in store.get_question_history(question_id)]


@router.get("/answers/{answer_id}/history")
def answer_history(
    answer_id: str,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in store.get_answer_history(answer_id)]
