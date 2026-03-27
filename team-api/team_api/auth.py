"""Authentication: password hashing, JWT creation and validation, API key support."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from acq_shared.store import Store

from .deps import get_store


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(username: str, *, secret: str, ttl_hours: int = 24) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str, *, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=["HS256"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class MeResponse(BaseModel):
    username: str
    created_at: str


def _get_jwt_secret() -> str:
    """Return ACQ_JWT_SECRET, failing loudly if unset."""
    secret = os.environ.get("ACQ_JWT_SECRET")
    if not secret:
        raise RuntimeError("ACQ_JWT_SECRET environment variable is required")
    return secret


def _get_api_keys() -> dict[str, str]:
    """Return the API key -> agent_name mapping from ACQ_API_KEYS env var.

    ACQ_API_KEYS is a JSON string like {"key1": "agent-name-1"}.
    Returns an empty dict if unset.
    """
    raw = os.environ.get("ACQ_API_KEYS", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def get_current_user(request: Request) -> str:
    """FastAPI dependency: validates Bearer JWT and returns username."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )
    token = auth_header.removeprefix("Bearer ")
    secret = _get_jwt_secret()
    try:
        payload = verify_token(token, secret=secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    return payload["sub"]


def get_agent_identity(request: Request) -> str:
    """FastAPI dependency: validates X-API-Key header and returns agent_name."""
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    api_keys = _get_api_keys()
    agent_name = api_keys.get(key)
    if agent_name is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return agent_name


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(request: LoginRequest, store: Store = Depends(get_store)) -> LoginResponse:
    user = store.get_user(request.username)
    if user is None or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_token(request.username, secret=_get_jwt_secret())
    return LoginResponse(token=token, username=request.username)


@router.get("/me")
def me(
    username: str = Depends(get_current_user), store: Store = Depends(get_store)
) -> MeResponse:
    user = store.get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return MeResponse(username=user["username"], created_at=user["created_at"])
