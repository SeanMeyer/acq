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
    # Questions come first, and each one arrives as a bundle: the pending
    # question plus the answers filed under it. The reviewer's verdict covers
    # the whole card, because approving an answer whose question was rejected
    # would leave the knowledge hanging off something nobody can reach. The
    # store enforces the other half of that rule — answers under a question
    # that is not yet live are never offered as standalone items, so they can
    # only ever be reviewed here, inside the bundle.
    for question in queue["questions"]:
        thread = store.get_question_thread(question.id, include_pending=True)
        answers = thread["answers"] if thread else []
        serialised = question.model_dump(mode="json")
        items.append(
            {
                "id": question.id,
                "type": "question",
                # content and question are the same row for a question item.
                # The duplication is deliberate: it gives the UI one item
                # shape for all three types, so the card that renders the
                # parent question never has to special-case which key to read.
                "content": serialised,
                "question": serialised,
                "answers": [t["answer"].model_dump(mode="json") for t in answers],
                "status": question.status,
            }
        )
    for answer in queue["answers"]:
        question = store.get_question(answer.question_id)
        items.append(
            {
                "id": answer.id,
                "type": "answer",
                "content": answer.model_dump(mode="json"),
                "question": question.model_dump(mode="json") if question else None,
                "answers": [],
                "status": answer.status,
            }
        )
    for comment in queue["comments"]:
        # For comments on answers, find the parent question
        parent_question = None
        if comment.parent_type == "answer":
            parent_answer = store.get_answer(comment.parent_id)
            if parent_answer:
                parent_question = store.get_question(parent_answer.question_id)
        elif comment.parent_type == "question":
            parent_question = store.get_question(comment.parent_id)
        items.append(
            {
                "id": comment.id,
                "type": "comment",
                "content": comment.model_dump(mode="json"),
                "question": (
                    parent_question.model_dump(mode="json") if parent_question else None
                ),
                "answers": [],
                "status": comment.status,
            }
        )
    return {"items": items, "total": len(items)}


# ------------------------------------------------------------------
# Approve / reject
#
# One pair of routes covers all three content types, and the id prefix tells
# the store which one it is looking at.
#
# For answers and comments, rejection doubles as the soft-delete mechanism:
# nothing is removed, the row just stops being visible, and approving it
# again restores it. Both therefore accept content in any status other than
# the one being applied.
#
# For a question the verdict is atomic over the whole review card. Approving
# opens the question and promotes its pending answers in the same
# transaction. Rejecting only marks the question deleted and deliberately
# leaves those answers pending: a rejected question is invisible and the
# pending queue refuses to surface answers under a question that is not live,
# so they are already unreachable, and leaving them untouched is what keeps
# the rejection reversible by a later approve.
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
        "total_pending": status["pending"] + status["pending_questions"],
        "total_unanswered": status["unanswered"],
        "pending_questions": status["pending_questions"],
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
