"""Authentication: GitHub OAuth, JWT creation and validation, API key support."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import bcrypt
import jwt
import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from acq_shared.store import Store

from .deps import get_store

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


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
def login(
    request: LoginRequest, store: Store = Depends(get_store)
) -> LoginResponse:
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


# ------------------------------------------------------------------
# GitHub OAuth
# ------------------------------------------------------------------


def _github_client_id() -> str:
    val = os.environ.get("GITHUB_CLIENT_ID", "")
    if not val:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    return val


def _github_client_secret() -> str:
    val = os.environ.get("GITHUB_CLIENT_SECRET", "")
    if not val:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    return val


def _callback_uri(request: Request) -> str:
    """Build the OAuth callback URI, respecting X-Forwarded-Proto from ISP."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}/auth/callback"


@router.get("/github")
def github_login(request: Request) -> RedirectResponse:
    """Redirect to GitHub OAuth authorize page."""
    params = urlencode({
        "client_id": _github_client_id(),
        "redirect_uri": _callback_uri(request),
        "scope": "read:user",
    })
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/callback")
def github_callback(
    code: str = Query(...),
    store: Store = Depends(get_store),
) -> RedirectResponse:
    """Exchange GitHub code for access token, create ACQ session JWT."""
    # Exchange code for GitHub access token
    resp = http_requests.post(
        GITHUB_TOKEN_URL,
        json={
            "client_id": _github_client_id(),
            "client_secret": _github_client_secret(),
            "code": code,
        },
        headers={"Accept": "application/json"},
        timeout=10,
    )
    data = resp.json()
    github_token = data.get("access_token")
    if not github_token:
        raise HTTPException(status_code=401, detail=data.get("error_description", "GitHub auth failed"))

    # Fetch GitHub user profile
    user_resp = http_requests.get(
        GITHUB_USER_URL,
        headers={"Authorization": f"Bearer {github_token}", "Accept": "application/json"},
        timeout=10,
    )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch GitHub user")
    gh_user = user_resp.json()
    username = gh_user["login"]

    # Ensure user exists in the store (auto-create on first login)
    if store.get_user(username) is None:
        store.create_user(username, password_hash="github-oauth")

    # Issue ACQ JWT
    token = create_token(username, secret=_get_jwt_secret())
    return RedirectResponse(f"/login?token={token}")
