"""Human-facing review and editorial routes (JWT auth)."""

from __future__ import annotations

from typing import Any

from acq_shared.store import Store
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .deps import get_store

router = APIRouter(tags=["review"])


# ------------------------------------------------------------------
# Pending queue
# ------------------------------------------------------------------


@router.get("/review/queue")
def review_queue(
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    queue = store.pending_queue()
    items: list[dict[str, Any]] = []
    for answer in queue["answers"]:
        question = store.get_question(answer.question_id)
        items.append(
            {
                "id": answer.id,
                "type": "answer",
                "content": answer.model_dump(mode="json"),
                "question": question.model_dump(mode="json") if question else None,
                "status": answer.status,
            }
        )
    for comment in queue["comments"]:
        # For comments on answers, find the parent question
        question = None
        if comment.parent_type == "answer":
            parent_answer = store.get_answer(comment.parent_id)
            if parent_answer:
                question = store.get_question(parent_answer.question_id)
        elif comment.parent_type == "question":
            question = store.get_question(comment.parent_id)
        items.append(
            {
                "id": comment.id,
                "type": "comment",
                "content": comment.model_dump(mode="json"),
                "question": question.model_dump(mode="json") if question else None,
                "status": comment.status,
            }
        )
    return {"items": items, "total": len(items)}


# ------------------------------------------------------------------
# Approve / reject
#
# Rejection is also the soft-delete mechanism for answers and comments:
# nothing is removed, the row just stops being visible, and approving it
# again restores it. Both therefore accept content in any status other than
# the one being applied.
# ------------------------------------------------------------------


@router.post("/review/{content_id}/approve")
def approve_content(
    content_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    result = store.approve_content(content_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Content is already approved")
    return {"id": content_id, "status": "approved"}


@router.post("/review/{content_id}/reject")
def reject_content(
    content_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    result = store.reject_content(content_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Content is already rejected")
    return {"id": content_id, "status": "rejected"}


# ------------------------------------------------------------------
# Stats dashboard
# ------------------------------------------------------------------


@router.get("/review/stats")
def review_stats(
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    status = store.get_status()
    tag_rows = store.list_tags()
    return {
        "total_questions": status["total_questions"],
        "total_answers": status["total_answers"],
        "total_pending": status["pending"],
        "total_unanswered": status["unanswered"],
        "tags": [t.model_dump() for t in tag_rows],
        "total_votes": status["total_votes"],
        "recent_activity": [],
        "vote_distribution": [],
    }


# ------------------------------------------------------------------
# Edit question / answer / comment
# ------------------------------------------------------------------


class EditBodyRequest(BaseModel):
    body: str


class EditQuestionRequest(BaseModel):
    """A partial update. Every omitted field is left untouched.

    ``tags``, when present, replaces the question's whole tag set rather than
    adding to it, so the client always sends the full list it wants.
    """

    body: str | None = None
    title: str | None = None
    tags: list[str] | None = None


@router.put("/questions/{question_id}")
def edit_question(
    question_id: str,
    request: EditQuestionRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    result = store.edit_question(
        question_id,
        request.body,
        user,
        "human",
        new_title=request.title,
        new_tags=request.tags,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return result.model_dump(mode="json")


@router.put("/answers/{answer_id}")
def edit_answer(
    answer_id: str,
    request: EditBodyRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    result = store.edit_answer(answer_id, request.body, user, "human")
    if result is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return result.model_dump(mode="json")


@router.put("/comments/{comment_id}")
def edit_comment(
    comment_id: str,
    request: EditBodyRequest,
    user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    result = store.edit_comment(comment_id, request.body, user, "human")
    if result is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return result.model_dump(mode="json")


# ------------------------------------------------------------------
# Delete / restore question
#
# Answers and comments reuse the reject and approve routes above; questions
# have no review lifecycle, so they get their own pair.
# ------------------------------------------------------------------


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    result = store.delete_question(question_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Question is already deleted")
    return {"id": question_id, "status": "deleted"}


@router.post("/questions/{question_id}/restore")
def restore_question(
    question_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    result = store.restore_question(question_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if result is False:
        raise HTTPException(status_code=409, detail="Question is not deleted")
    return {"id": question_id, "status": "open"}


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
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    result = store.pin_answer(question_id, request.answer_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return result.model_dump(mode="json")


@router.delete("/questions/{question_id}/pin")
def unpin_answer(
    question_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
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
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in store.get_question_history(question_id)]


@router.get("/answers/{answer_id}/history")
def answer_history(
    answer_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in store.get_answer_history(answer_id)]


@router.get("/comments/{comment_id}/history")
def comment_history(
    comment_id: str,
    _user: str = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in store.get_comment_history(comment_id)]
