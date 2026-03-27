"""HTTP client for the acq Team API.

Wraps all team API endpoints with graceful degradation: transport errors
return None instead of raising, so the MCP server can fall back to local-only
mode. HTTP errors (4xx/5xx) are returned as structured error dicts.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5.0

_TRANSPORT_ERRORS = (httpx.TransportError, httpx.TimeoutException)


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

    async def __aenter__(self) -> "TeamClient":
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
    ) -> list[dict] | None:
        params: dict[str, object] = {"q": query, "limit": limit}
        if tags:
            params["tags"] = tags
        if language:
            params["language"] = language
        if framework:
            params["framework"] = framework
        try:
            resp = await self._client.get("/search", params=params)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API search unreachable", exc_info=True)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Team API search error %d", exc.response.status_code)
            return None
        except Exception:
            logger.warning("Team API search failed", exc_info=True)
            return None

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
    ) -> dict | None:
        payload: dict[str, object] = {
            "title": title,
            "body": body,
            "created_by": created_by,
            "tags": tags,
            "force_create": force_create,
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
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API create_question unreachable", exc_info=True)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Team API create_question error %d", exc.response.status_code)
            return {"error": exc.response.text, "status_code": exc.response.status_code}
        except Exception:
            logger.warning("Team API create_question failed", exc_info=True)
            return None

    async def create_answer(
        self,
        question_id: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> dict | None:
        payload = {
            "body": body,
            "created_by": created_by,
            "supervised": supervised,
        }
        try:
            resp = await self._client.post(
                f"/questions/{question_id}/answers", json=payload
            )
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API create_answer unreachable", exc_info=True)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Team API create_answer error %d", exc.response.status_code)
            return {"error": exc.response.text, "status_code": exc.response.status_code}
        except Exception:
            logger.warning("Team API create_answer failed", exc_info=True)
            return None

    async def cast_vote(
        self,
        target_id: str,
        value: int,
        voter_id: str,
    ) -> dict | None:
        payload = {"value": value, "voter_id": voter_id}
        try:
            resp = await self._client.post("/vote", json=payload)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API cast_vote unreachable", exc_info=True)
            return None
        except httpx.HTTPStatusError as exc:
            # 409 = already voted, 429 = rate limited — caller handles these gracefully.
            return {"error": exc.response.text, "status_code": exc.response.status_code}
        except Exception:
            logger.warning("Team API cast_vote failed", exc_info=True)
            return None

    async def create_comment(
        self,
        parent_id: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> dict | None:
        payload = {
            "body": body,
            "created_by": created_by,
            "supervised": supervised,
        }
        try:
            resp = await self._client.post("/comments", json=payload)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API create_comment unreachable", exc_info=True)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Team API create_comment error %d", exc.response.status_code)
            return {"error": exc.response.text, "status_code": exc.response.status_code}
        except Exception:
            logger.warning("Team API create_comment failed", exc_info=True)
            return None

    async def export_since(self, since: str | None = None) -> dict | None:
        params = {}
        if since:
            params["since"] = since
        try:
            resp = await self._client.get("/export", params=params)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API export unreachable", exc_info=True)
            return None
        except Exception:
            logger.warning("Team API export failed", exc_info=True)
            return None

    async def reflect(self, session_context: str) -> dict | None:
        payload = {"session_context": session_context}
        try:
            resp = await self._client.post("/reflect", json=payload)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API reflect unreachable", exc_info=True)
            return None
        except Exception:
            logger.warning("Team API reflect failed", exc_info=True)
            return None

    async def get_status(self) -> dict | None:
        try:
            resp = await self._client.get("/status")
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API get_status unreachable", exc_info=True)
            return None
        except Exception:
            logger.warning("Team API get_status failed", exc_info=True)
            return None

    async def get_tags(self, query: str = "") -> list[dict] | None:
        params = {}
        if query:
            params["q"] = query
        try:
            resp = await self._client.get("/tags", params=params)
            resp.raise_for_status()
            return resp.json()
        except _TRANSPORT_ERRORS:
            logger.warning("Team API get_tags unreachable", exc_info=True)
            return None
        except Exception:
            logger.warning("Team API get_tags failed", exc_info=True)
            return None
