"""Tests for the acq Team API client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from acq_mcp.team_client import TeamClient

_MOCK_REQUEST = httpx.Request("GET", "http://test")


def _mock_response(status_code: int, json: object) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json,
        request=_MOCK_REQUEST,
    )


async def _raise_connect_error(*_args: object, **_kwargs: object) -> None:
    raise httpx.ConnectError("Connection refused")


def _async_returning(response: httpx.Response):
    async def handler(*_args: object, **_kwargs: object) -> httpx.Response:
        return response

    return handler


@pytest.fixture
async def client() -> AsyncIterator[TeamClient]:
    c = TeamClient(base_url="http://localhost:8742", api_key="test-key")
    yield c
    await c.close()


class TestTeamClientInit:
    async def test_base_url_property(self) -> None:
        async with TeamClient(base_url="http://localhost:8742") as c:
            assert c.base_url == "http://localhost:8742"

    async def test_context_manager_closes_client(self) -> None:
        async with TeamClient(base_url="http://localhost:8742") as c:
            pass
        assert c._client.is_closed

    async def test_api_key_sent_in_header(self) -> None:
        c = TeamClient(base_url="http://localhost:8742", api_key="secret-key")
        assert c._client.headers.get("x-api-key") == "secret-key"
        await c.close()


class TestHealth:
    async def test_returns_true_on_200(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(200, {})))
        assert await client.health() is True

    async def test_returns_false_on_non_200(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(503, {})))
        assert await client.health() is False

    async def test_returns_false_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _raise_connect_error)
        assert await client.health() is False


class TestSearch:
    async def test_returns_results_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = [{"id": "q_1", "title": "How to pool?"}]
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(200, data)))
        result = await client.search("connection pool")
        assert result.ok
        assert len(result.data) == 1
        assert result.data[0]["id"] == "q_1"

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _raise_connect_error)
        result = await client.search("query")
        assert not result.ok
        assert result.warnings

    async def test_returns_error_on_http_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(500, {"detail": "error"})))
        result = await client.search("query")
        assert not result.ok
        assert result.status_code == 500


class TestCreateQuestion:
    async def test_returns_dict_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"id": "q_team_1", "title": "Q", "similar_questions": []}
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(201, data)))
        result = await client.create_question(title="Q", body="B", created_by="a", tags=["t"])
        assert result.ok
        assert result.data["id"] == "q_team_1"

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _raise_connect_error)
        result = await client.create_question(title="Q", body="B", created_by="a", tags=["t"])
        assert not result.ok
        assert result.warnings

    async def test_returns_error_on_http_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            client._client,
            "post",
            _async_returning(_mock_response(422, {"detail": "Validation error"})),
        )
        result = await client.create_question(title="Q", body="B", created_by="a", tags=["t"])
        assert not result.ok
        assert result.status_code == 422
        assert result.error


class TestCreateAnswer:
    async def test_returns_dict_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"id": "a_team_1", "status": "pending"}
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(201, data)))
        result = await client.create_answer("q_1", "Answer body", "agent-1")
        assert result.ok
        assert result.data["id"] == "a_team_1"

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _raise_connect_error)
        result = await client.create_answer("q_1", "B", "a")
        assert not result.ok

    async def test_returns_error_on_404(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(404, {"detail": "Not found"})))
        result = await client.create_answer("q_missing", "B", "a")
        assert not result.ok
        assert result.status_code == 404


class TestCastVote:
    async def test_returns_vote_counts_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"upvotes": 5, "downvotes": 1}
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(200, data)))
        result = await client.cast_vote("q_1", "question", 1, "agent-1")
        assert result.ok
        assert result.data["upvotes"] == 5

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _raise_connect_error)
        result = await client.cast_vote("q_1", "question", 1, "a")
        assert not result.ok

    async def test_returns_structured_error_on_409(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            client._client,
            "post",
            _async_returning(_mock_response(409, {"detail": "Already voted"})),
        )
        result = await client.cast_vote("q_1", "question", 1, "a")
        assert not result.ok
        assert result.status_code == 409

    async def test_returns_structured_error_on_429(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            client._client,
            "post",
            _async_returning(_mock_response(429, {"detail": "Rate limited"})),
        )
        result = await client.cast_vote("q_1", "question", 1, "a")
        assert not result.ok
        assert result.status_code == 429


class TestCreateComment:
    async def test_returns_dict_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"id": "c_team_1", "status": "pending"}
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(201, data)))
        result = await client.create_comment("q_1", "question", "Great question!", "agent-1")
        assert result.ok
        assert result.data["id"] == "c_team_1"

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _raise_connect_error)
        result = await client.create_comment("q_1", "question", "C", "a")
        assert not result.ok


class TestReflect:
    async def test_returns_dict_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"candidates": [], "message": "Done"}
        monkeypatch.setattr(client._client, "post", _async_returning(_mock_response(200, data)))
        result = await client.reflect("session context")
        assert result.ok
        assert "message" in result.data

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "post", _raise_connect_error)
        result = await client.reflect("context")
        assert not result.ok


class TestGetStatus:
    async def test_returns_dict_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"questions": 10, "answers": 25}
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(200, data)))
        result = await client.get_status()
        assert result.ok
        assert result.data["questions"] == 10

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _raise_connect_error)
        result = await client.get_status()
        assert not result.ok


class TestGetTags:
    async def test_returns_tags_on_success(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        data = [{"name": "python", "usage_count": 42}]
        monkeypatch.setattr(client._client, "get", _async_returning(_mock_response(200, data)))
        result = await client.get_tags("py")
        assert result.ok
        assert result.data[0]["name"] == "python"

    async def test_returns_error_on_connection_error(self, client: TeamClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client._client, "get", _raise_connect_error)
        result = await client.get_tags()
        assert not result.ok


class TestEditPayload:
    """What each edit form puts on the wire, since the server decides by it."""

    @staticmethod
    async def _sent(call) -> list[dict]:
        sent: list[dict] = []

        def handle(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "x", "body": "b"})

        c = TeamClient(base_url="http://team")
        c._client = httpx.AsyncClient(base_url="http://team", transport=httpx.MockTransport(handle))
        async with c:
            await call(c)
        return sent

    async def test_passage_edits_send_the_passage_not_a_body(self) -> None:
        async def edits(c: TeamClient) -> None:
            await c.edit_answer("a_1", old_text="old", new_text="new")
            await c.edit_comment("c_1", old_text="old", new_text="")
            await c.edit_question("q_1", title="T", old_text="old", new_text="new")

        assert await self._sent(edits) == [
            {"old_text": "old", "new_text": "new"},
            {"old_text": "old", "new_text": ""},
            {"old_text": "old", "new_text": "new", "title": "T"},
        ]

    async def test_whole_body_edit_sends_only_the_body(self) -> None:
        async def edits(c: TeamClient) -> None:
            await c.edit_answer("a_1", "whole new body")

        assert await self._sent(edits) == [{"body": "whole new body"}]
