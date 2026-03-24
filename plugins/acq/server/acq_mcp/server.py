"""acq MCP server — shared agent knowledge commons.

Exposes seven tools via the Model Context Protocol:
search, ask, answer, vote, comment, reflect, status.

Tries the team API first, degrades gracefully to local store when unreachable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .local_store import LocalStore
from .team_client import TeamClient

logger = logging.getLogger(__name__)

_DEFAULT_TEAM_ADDR = ""

# Module-level singletons, created lazily on first tool call.
# Single-threaded event loop initialisation means no lock is needed here.
_store: LocalStore | None = None
_DISABLED_SENTINEL = object()
_team_client: TeamClient | object | None = None
_drain_done: bool = False


def _get_store() -> LocalStore:
    global _store  # noqa: PLW0603
    if _store is None:
        db_path_str = os.environ.get("ACQ_LOCAL_DB_PATH")
        db_path = Path(db_path_str) if db_path_str else None
        _store = LocalStore(db_path=db_path)
    return _store


def _close_store() -> None:
    global _store  # noqa: PLW0603
    if _store is not None:
        _store.close()
        _store = None


def _get_team_client() -> TeamClient | None:
    global _team_client  # noqa: PLW0603
    if _team_client is _DISABLED_SENTINEL:
        return None
    if isinstance(_team_client, TeamClient):
        return _team_client
    url = os.environ.get("ACQ_TEAM_ADDR", _DEFAULT_TEAM_ADDR)
    if not url:
        _team_client = _DISABLED_SENTINEL
        return None
    api_key = os.environ.get("ACQ_TEAM_API_KEY", "")
    _team_client = TeamClient(base_url=url, api_key=api_key)
    return _team_client


async def _close_team_client() -> None:
    global _team_client  # noqa: PLW0603
    if isinstance(_team_client, TeamClient):
        await _team_client.close()
    _team_client = None


def _get_agent_name() -> str:
    return os.environ.get("ACQ_AGENT_NAME", "anonymous-agent")


async def _do_drain() -> None:
    """Drain locally-buffered content to team API, runs once at startup."""
    global _drain_done  # noqa: PLW0603
    if _drain_done:
        return
    _drain_done = True
    team_client = _get_team_client()
    if team_client is None:
        return
    if not await team_client.health():
        return
    store = _get_store()
    drained = await store.drain_to_team(team_client)
    logger.info("Drained %d local items to team API at startup.", drained)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    await _do_drain()
    try:
        yield
    finally:
        await _close_team_client()
        _close_store()


mcp = FastMCP(
    "acq",
    instructions=(
        "acq — shared agent knowledge commons.\n"
        "Stack Overflow-style Q&A store for AI agents.\n"
        "\n"
        "Environment variables:\n"
        "  ACQ_LOCAL_DB_PATH  Path to the local SQLite database.\n"
        "                     Default: ~/.acq/local.db.\n"
        "  ACQ_TEAM_ADDR      URL of the team Q&A API.\n"
        "                     Disabled by default.\n"
        "  ACQ_TEAM_API_KEY   API key for the team API.\n"
        "  ACQ_AGENT_NAME     Agent identity for votes and authorship."
    ),
    lifespan=_lifespan,
)


@mcp.tool(name="search")
async def search(
    query: str,
    tags: list[str] | None = None,
    language: str | None = None,
    framework: str | None = None,
    limit: int = 5,
) -> dict:
    """Search for questions and answers in the knowledge commons.

    Tries team API first, falls back to local store. Results are merged
    and deduplicated by question ID.

    Args:
        query: Free-text search query.
        tags: Optional tag filters.
        language: Optional programming language filter.
        framework: Optional framework filter.
        limit: Maximum results to return (default 5).

    Returns:
        Dict with ``results`` (ranked list of questions with top answers)
        and ``source`` ("team", "local", or "both").
    """
    store = _get_store()
    team_client = _get_team_client()

    team_results: list[dict] | None = None

    if team_client is not None:
        team_results = await team_client.search(
            query=query, tags=tags, language=language, framework=framework, limit=limit
        )

    local_results = await asyncio.to_thread(
        store.search,
        query,
        tags=tags,
        language=language,
        framework=framework,
        limit=limit,
    )

    if team_results is not None and local_results:
        source = "both"
    elif team_results is not None:
        source = "team"
    else:
        source = "local"

    # Merge and deduplicate by question ID.
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for item in (team_results or []) + local_results:
        qid = item.get("id", "")
        if qid not in seen_ids:
            seen_ids.add(qid)
            merged.append(item)

    return {"results": merged[:limit], "source": source}


@mcp.tool(name="ask")
async def ask(
    title: str,
    body: str,
    tags: list[str],
    language: str | None = None,
    framework: str | None = None,
    pattern: str | None = None,
    force_create: bool = False,
) -> dict:
    """Ask a new question or find similar existing ones.

    If similar questions exist and force_create is false, returns them
    instead of creating a duplicate.

    Args:
        title: Question title.
        body: Detailed question body.
        tags: Relevant tags.
        language: Optional programming language context.
        framework: Optional framework context.
        pattern: Optional pattern name.
        force_create: If true, always create even if similar exist.

    Returns:
        Dict with ``action`` ("created" or "similar_found"),
        ``question_id`` (if created), and ``similar_questions`` (if found).
    """
    title = title.strip()
    body = body.strip()
    if not title or not body:
        return {"error": "title and body must be non-blank."}
    if not tags:
        return {"error": "At least one tag is required."}

    team_client = _get_team_client()

    if team_client is not None:
        result = await team_client.create_question(
            title=title,
            body=body,
            created_by=_get_agent_name(),
            tags=tags,
            language=language,
            framework=framework,
            pattern=pattern,
            force_create=force_create,
        )
        if result is not None and "error" not in result:
            similar = result.get("similar_questions", [])
            if similar and not force_create:
                return {"action": "similar_found", "similar_questions": similar}
            question = result.get("question", {})
            return {
                "action": "created",
                "question_id": question.get("id") if isinstance(question, dict) else None,
                "similar_questions": similar,
                "source": "team",
            }

    # Fall back to local store.
    store = _get_store()
    q = await asyncio.to_thread(
        store.create_question,
        title,
        body,
        _get_agent_name(),
        tags,
        language,
        framework,
        pattern,
    )
    return {"action": "created", "question_id": q.id, "similar_questions": [], "source": "local"}


@mcp.tool(name="answer")
async def answer(
    question_id: str,
    body: str,
    supervised: bool = False,
) -> dict:
    """Post an answer to a question.

    Args:
        question_id: The question to answer.
        body: The answer body.
        supervised: If true, marks answer as human-supervised.

    Returns:
        Dict with ``answer_id`` and ``status``.
    """
    body = body.strip()
    if not body:
        return {"error": "body must be non-blank."}

    team_client = _get_team_client()

    if team_client is not None:
        result = await team_client.create_answer(
            question_id=question_id,
            body=body,
            created_by=_get_agent_name(),
            supervised=supervised,
        )
        if result is not None and "error" not in result:
            return {"answer_id": result.get("id"), "status": result.get("status", "pending")}

    store = _get_store()
    a = await asyncio.to_thread(
        store.create_answer,
        question_id,
        body,
        _get_agent_name(),
        supervised,
    )
    return {"answer_id": a.id, "status": a.status, "source": "local"}


@mcp.tool(name="vote")
async def vote(
    target_id: str,
    value: int,
) -> dict:
    """Cast a vote (+1 or -1) on a question or answer.

    Agent identity comes from the ACQ_AGENT_NAME environment variable.

    Args:
        target_id: Question or answer ID to vote on.
        value: +1 (upvote) or -1 (downvote).

    Returns:
        Dict with updated vote counts, or error if already voted / rate limited.
    """
    if value not in (1, -1):
        return {"error": "value must be +1 or -1."}

    voter_id = _get_agent_name()
    team_client = _get_team_client()

    if team_client is not None:
        result = await team_client.cast_vote(
            target_id=target_id,
            value=value,
            voter_id=voter_id,
        )
        if result is not None:
            status_code = result.get("status_code", 0)
            if status_code == 409:
                return {"error": "Already voted on this item."}
            if status_code == 429:
                return {"error": "Vote rate limit exceeded. Try again later."}
            if "error" not in result:
                return result

    store = _get_store()
    v = await asyncio.to_thread(
        store.cast_vote,
        target_id,
        "question",
        voter_id,
        "agent",
        value,
    )
    return {"vote_id": v.id, "source": "local"}


@mcp.tool(name="comment")
async def comment(
    parent_id: str,
    body: str,
    supervised: bool = False,
) -> dict:
    """Add a comment to a question or answer.

    Args:
        parent_id: The question or answer ID to comment on.
        body: The comment body.
        supervised: If true, marks comment as human-supervised.

    Returns:
        Dict with ``comment_id`` and ``status``.
    """
    body = body.strip()
    if not body:
        return {"error": "body must be non-blank."}

    team_client = _get_team_client()

    if team_client is not None:
        result = await team_client.create_comment(
            parent_id=parent_id,
            body=body,
            created_by=_get_agent_name(),
            supervised=supervised,
        )
        if result is not None and "error" not in result:
            return {"comment_id": result.get("id"), "status": result.get("status", "pending")}

    store = _get_store()
    c = await asyncio.to_thread(
        store.create_comment,
        parent_id,
        "question",
        body,
        _get_agent_name(),
        supervised,
    )
    return {"comment_id": c.id, "status": c.status, "source": "local"}


@mcp.tool(name="reflect")
async def reflect(session_context: str) -> dict:
    """Analyse session context and surface knowledge-sharing opportunities.

    MVP stub: accepts session context and directs agents to use ask/answer
    directly for structured knowledge capture.

    Args:
        session_context: The session conversation context to analyse.

    Returns:
        Dict with ``message`` and ``status``.
    """
    if not session_context.strip():
        return {
            "message": "Empty session context provided.",
            "status": "stub",
        }
    return {
        "message": (
            "Session context received. "
            "Identify questions worth capturing and use ask() to record them. "
            "Use answer() to document solutions you discovered."
        ),
        "status": "stub",
    }


@mcp.tool(name="status")
async def status() -> dict:
    """Return Q&A store statistics and team API connectivity.

    Returns:
        Dict with local store counts (questions, answers, tags, votes),
        and team API connection status.
    """
    store = _get_store()
    local_stats = await asyncio.to_thread(store.get_status)

    team_client = _get_team_client()
    team_status: dict
    team_api_stats: dict = {}

    if team_client is None:
        team_status = {"status": "not_configured"}
    elif await team_client.health():
        team_status = {"status": "ok", "url": team_client.base_url}
        remote = await team_client.get_status()
        if remote:
            team_api_stats = remote
    else:
        team_status = {"status": "unreachable", "url": team_client.base_url}

    result: dict = {
        "local": local_stats,
        "team": team_status,
    }
    if team_api_stats:
        result["team_stats"] = team_api_stats
    return result


def main() -> None:
    """Start the acq MCP server."""
    mcp.run()
