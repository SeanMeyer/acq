"""Tag management routes (JWT auth)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .deps import get_store
from .store import TeamStore

router = APIRouter(tags=["tags"])


class MergeTagsRequest(BaseModel):
    source_id: str
    target_id: str


@router.post("/tags/merge")
def merge_tags(
    request: MergeTagsRequest,
    _user: str = Depends(get_current_user),
    store: TeamStore = Depends(get_store),
) -> dict[str, Any]:
    tags = store.list_tags()
    tag_ids = {t.id for t in tags}
    if request.source_id not in tag_ids:
        raise HTTPException(status_code=404, detail="Source tag not found")
    if request.target_id not in tag_ids:
        raise HTTPException(status_code=404, detail="Target tag not found")
    store.merge_tags(request.source_id, request.target_id)
    updated_tags = store.list_tags()
    target = next((t for t in updated_tags if t.id == request.target_id), None)
    return {"merged": True, "target": target.model_dump() if target else None}
