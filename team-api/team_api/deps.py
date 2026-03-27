"""FastAPI dependencies shared across routers."""

from fastapi import Request

from acq_shared.store import Store


def get_store(request: Request) -> Store:
    """FastAPI dependency: returns the Store from app.state."""
    return request.app.state.store
