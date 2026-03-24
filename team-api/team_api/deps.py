"""FastAPI dependencies shared across routers."""

from fastapi import Request

from .store import TeamStore


def get_store(request: Request) -> TeamStore:
    """FastAPI dependency: returns the TeamStore from app.state."""
    return request.app.state.store
