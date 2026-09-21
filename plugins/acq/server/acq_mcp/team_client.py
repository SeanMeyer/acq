"""HTTP client for the acq Team API.

Wraps all team API endpoints with graceful degradation: transport errors
return None instead of raising, so the MCP server can fall back to local-only
mode. HTTP errors (4xx/5xx) are returned as structured error dicts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5.0

_TRANSPORT_ERRORS = (httpx.TransportError, httpx.TimeoutException)


@dataclass(frozen=True, slots=True)
class ApiResult:
    """Structured result from a Team API call.

    Ported from upstream cq's structured-warnings pattern: callers get
    success data, HTTP error details, AND accumulated warnings in one
    object instead of guessing whether the return is None, a dict with
    ``error``, or a success payload.

    Usage::

        r = await client.create_question(...)
        if r.ok:
            process(r.data)
        elif r.status_code == 409:
            handle_conflict(r.error)
        if r.warnings:
            log_warnings(r.warnings)
    """

    data: dict | list | None = None
    error: str | None = None
    status_code: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.data is not None

    @staticmethod
    def success(data: dict | list) -> ApiResult:
        return ApiResult(data=data)

    @staticmethod
    def transport_error(method: str, exc: Exception) -> ApiResult:
        msg = f"Team API {method} unreachable: {exc}"
        logger.warning(msg, exc_info=True)
        return ApiResult(error=msg, warnings=[msg])

    @staticmethod
    def http_error(method: str, exc: httpx.HTTPStatusError) -> ApiResult:
        msg = f"Team API {method} error {exc.response.status_code}"
        logger.warning(msg)
        return ApiResult(
            error=exc.response.text,
            status_code=exc.response.status_code,
            warnings=[msg],
        )

    @staticmethod
    def unexpected_error(method: str, exc: Exception) -> ApiResult:
        msg = f"Team API {method} failed: {exc}"
        logger.warning(msg, exc_info=True)
        return ApiResult(error=msg, warnings=[msg])


class TeamClient:
    """Async HTTP client for the acq Team API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"X-API-Key": api_key} if api_key else {},
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    async def __aenter__(self) -> TeamClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def search(
        self,
        query: str,
        tags: list[str] | None = None,
        language: str | None = None,
        framework: str | None = None,
        limit: int = 5,
    ) -> ApiResult:
        params: dict[str, str | int | list[str]] = {"q": query, "limit": limit}
        if tags:
            params["tags"] = tags
        if language:
            params["language"] = language
        if framework:
            params["framework"] = framework
        try:
            resp = await self._client.get("/search", params=params)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("search", exc)
        except httpx.HTTPStatusError as exc:
            return ApiResult.http_error("search", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("search", exc)

    async def create_question(
        self,
        title: str,
        body: str,
        created_by: str,
        tags: list[str],
        language: str | None = None,
        framework: str | None = None,
        pattern: str | None = None,
        force_create: bool = False,
        supervised: bool = False,
    ) -> ApiResult:
        payload: dict[str, object] = {
            "title": title,
            "body": body,
            "created_by": created_by,
            "tags": tags,
            "force_create": force_create,
            "supervised": supervised,
        }
        if language:
            payload["language"] = language
        if framework:
            payload["framework"] = framework
        if pattern:
            payload["pattern"] = pattern
        try:
            resp = await self._client.post("/questions", json=payload)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("create_question", exc)
        except httpx.HTTPStatusError as exc:
            return ApiResult.http_error("create_question", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("create_question", exc)

    async def create_answer(
        self,
        question_id: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> ApiResult:
        payload = {
            "body": body,
            "created_by": created_by,
            "supervised": supervised,
        }
        try:
            resp = await self._client.post(f"/questions/{question_id}/answers", json=payload)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("create_answer", exc)
        except httpx.HTTPStatusError as exc:
            return ApiResult.http_error("create_answer", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("create_answer", exc)

    async def cast_vote(
        self,
        target_id: str,
        target_type: str,
        value: int,
        voter_id: str,
    ) -> ApiResult:
        payload = {"target_id": target_id, "target_type": target_type, "value": value}
        try:
            resp = await self._client.post("/vote", json=payload)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("cast_vote", exc)
        except httpx.HTTPStatusError as exc:
            # 409 = already voted, 429 = rate limited — caller handles these gracefully.
            return ApiResult.http_error("cast_vote", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("cast_vote", exc)

    async def create_comment(
        self,
        parent_id: str,
        parent_type: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> ApiResult:
        payload = {
            "parent_id": parent_id,
            "parent_type": parent_type,
            "body": body,
            "created_by": created_by,
            "supervised": supervised,
        }
        try:
            resp = await self._client.post("/comments", json=payload)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("create_comment", exc)
        except httpx.HTTPStatusError as exc:
            return ApiResult.http_error("create_comment", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("create_comment", exc)

    async def export_since(self, since: str | None = None) -> ApiResult:
        params = {}
        if since:
            params["since"] = since
        try:
            resp = await self._client.get("/export", params=params)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("export", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("export", exc)

    async def reflect(self, session_context: str) -> ApiResult:
        payload = {"session_context": session_context}
        try:
            resp = await self._client.post("/reflect", json=payload)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("reflect", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("reflect", exc)

    async def get_status(self) -> ApiResult:
        try:
            resp = await self._client.get("/status")
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("get_status", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("get_status", exc)

    async def get_tags(self, query: str = "") -> ApiResult:
        params = {}
        if query:
            params["q"] = query
        try:
            resp = await self._client.get("/tags", params=params)
            resp.raise_for_status()
            return ApiResult.success(resp.json())
        except _TRANSPORT_ERRORS as exc:
            return ApiResult.transport_error("get_tags", exc)
        except Exception as exc:
            return ApiResult.unexpected_error("get_tags", exc)
