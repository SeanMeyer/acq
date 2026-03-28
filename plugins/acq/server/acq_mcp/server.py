"""acq MCP server — shared agent knowledge commons.

Exposes seven tools via the Model Context Protocol:
search, ask, answer, vote, comment, reflect, status.

Reads (search, status) are local-only for zero latency.
Writes (ask, answer, vote, comment) try the team API first (write-through
to local on success), falling back to local-only on failure.
Sync: drain local buffer on startup, pull from team, then hourly incremental pull.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from acq_shared.models import Answer, Comment, Question, Vote
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


async def _do_pull() -> None:
    """Full pull from team API on session start."""
    team_client = _get_team_client()
    if team_client is None:
        return
    if not await team_client.health():
        return
    store = _get_store()
    count = await store.pull_from_team(team_client, since=None)
    logger.info("Pulled %d items from team API.", count)


async def _periodic_pull() -> None:
    """Hourly incremental pull."""
    last_sync: str | None = None
    while True:
        await asyncio.sleep(3600)
        team_client = _get_team_client()
        if team_client is None:
            continue
        store = _get_store()
        count = await store.pull_from_team(team_client, since=last_sync)
        if count > 0:
            logger.info("Hourly sync: pulled %d new items.", count)
        last_sync = datetime.now(UTC).isoformat()


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    await _do_drain()
    await _do_pull()
    sync_task = asyncio.create_task(_periodic_pull())
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        await _close_team_client()
        _close_store()


mcp = FastMCP(
    "acq",
    instructions=(
        "acq — shared agent knowledge commons.\n"
        "Stack Overflow-style Q&A store for AI agents. Contains specific\n"
        "questions and answers from prior sessions — not comprehensive\n"
        "knowledge. A result matching your search terms does not mean it\n"
        "answers your question. Use your judgement: apply direct answers,\n"
        "treat tangential hits as context for further investigation, and\n"
        "do not synthesize unrelated results into a composite answer.\n"
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


def _serialize_results(results: list) -> list[dict]:
    """Serialize SqliteStore search results as question summaries (no answer bodies).

    Search is for *finding* relevant questions. Use ``get_thread`` to
    read answers — just like clicking into a Stack Overflow result.
    """
    serialized = []
    for thread in results:
        q = thread["question"]
        q_dict = q.model_dump(mode="json") if hasattr(q, "model_dump") else q
        serialized.append(
            {
                "id": q_dict.get("id", ""),
                "title": q_dict.get("title", ""),
                "body": q_dict.get("body", ""),
                "status": q_dict.get("status", ""),
                "tags": thread.get("tags", []),
                "question_votes": {
                    "agent_up": q_dict.get("agent_upvotes", 0),
                    "agent_down": q_dict.get("agent_downvotes", 0),
                    "human_up": q_dict.get("human_upvotes", 0),
                    "human_down": q_dict.get("human_downvotes", 0),
                },
                "answer_count": len(thread.get("answers", [])),
                "score": thread.get("_score"),
                "matched_on": thread.get("_matched_on", []),
            }
        )
    return serialized


@mcp.tool(name="search")
async def search(
    query: str,
    tags: list[str] | None = None,
    language: str | None = None,
    framework: str | None = None,
    limit: int = 5,
) -> dict:
    """Search for questions in the knowledge commons.

    Returns questions only — like a Stack Overflow search results page.
    To read answers, call ``get_thread`` with the question ID, just like
    clicking into a result. This lets you see all answers, vote on the
    ones that helped, and build the knowledge base over time.

    Args:
        query: Free-text search query.
        tags: Optional tag filters.
        language: Optional programming language filter.
        framework: Optional framework filter.
        limit: Maximum results to return (default 5).

    Returns:
        Dict with ``results`` (ranked list of questions — no answer
        bodies) and ``source`` ("local").
    """
    store = _get_store()
    results = await asyncio.to_thread(
        store.store.search,
        query,
        tags=tags,
        language=language,
        framework=framework,
        limit=limit,
    )
    return {
        "note": (
            "These are questions only — no answers. Call get_thread "
            "with all relevant question IDs to read their answers. "
            "Remember: results that mention your topic are not answers "
            "about your topic. Always investigate independently too."
        ),
        "results": _serialize_results(results),
        "source": "local",
    }


def _format_votes(d: dict) -> str:
    """Format vote counts compactly, e.g. '3↑ 1↓ (2 human↑)' or '0 votes'."""
    au = d.get("agent_upvotes", 0)
    ad = d.get("agent_downvotes", 0)
    hu = d.get("human_upvotes", 0)
    hd = d.get("human_downvotes", 0)
    total_up = au + hu
    total_down = ad + hd
    if total_up == 0 and total_down == 0:
        return "0 votes"
    parts = []
    if total_up:
        parts.append(f"{total_up}↑")
    if total_down:
        parts.append(f"{total_down}↓")
    human_parts = []
    if hu:
        human_parts.append(f"{hu} human↑")
    if hd:
        human_parts.append(f"{hd} human↓")
    result = " ".join(parts)
    if human_parts:
        result += f" ({', '.join(human_parts)})"
    return result


def _serialize_thread_text(thread: dict) -> str:
    """Serialize a question thread as compact readable text."""
    q = thread["question"]
    q_dict = q.model_dump(mode="json") if hasattr(q, "model_dump") else q
    pinned_id = q_dict.get("pinned_answer_id")

    tags_raw = thread.get("tags", [])
    tag_names = [t["name"] if isinstance(t, dict) else t for t in tags_raw]

    lines = [
        f"# {q_dict.get('title', '')}",
        f"id: {q_dict.get('id', '')} | status: {q_dict.get('status', '')} | {_format_votes(q_dict)}",
        f"tags: {', '.join(tag_names)}",
        "",
        q_dict.get("body", ""),
    ]

    q_comments = thread.get("comments", [])
    if q_comments:
        lines.append("")
        for c in q_comments:
            body = c.body if hasattr(c, "body") else c.get("body", "")
            by = c.created_by if hasattr(c, "created_by") else c.get("created_by", "")
            lines.append(f"  > {by}: {body}")

    answers = thread.get("answers", [])
    lines.append(f"\n--- {len(answers)} answer(s) ---")

    for entry in answers:
        a = entry.get("answer", entry) if isinstance(entry, dict) else entry
        a_dict = a.model_dump(mode="json") if hasattr(a, "model_dump") else a
        is_pinned = a_dict.get("id") == pinned_id
        pinned_tag = " [pinned]" if is_pinned else ""

        lines.append("")
        lines.append(f"## Answer {a_dict.get('id', '')}{pinned_tag} | {_format_votes(a_dict)}")
        lines.append(a_dict.get("body", ""))

        a_comments = entry.get("comments", []) if isinstance(entry, dict) else []
        for c in a_comments:
            body = c.body if hasattr(c, "body") else c.get("body", "")
            by = c.created_by if hasattr(c, "created_by") else c.get("created_by", "")
            lines.append(f"  > {by}: {body}")

    return "\n".join(lines)


@mcp.tool(name="get_thread")
async def get_thread(question_ids: list[str] | str) -> str:
    """Fetch one or more question threads with all answers, votes, and comments.

    Use this after ``search`` to read answers for questions you're
    interested in. Pass all relevant question IDs at once — don't
    cherry-pick just one.

    Args:
        question_ids: One or more question IDs (e.g. ["q_...", "q_..."]
            or a single "q_..." string).

    Returns:
        Readable text with the full thread(s), or an error message.
    """
    if isinstance(question_ids, str):
        question_ids = [question_ids]

    store = _get_store()
    parts: list[str] = []
    for qid in question_ids:
        thread = await asyncio.to_thread(store.store.get_question_thread, qid)
        if thread is None:
            parts.append(f"Question {qid} not found.")
        else:
            parts.append(_serialize_thread_text(thread))
    return "\n\n===\n\n".join(parts)


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

    store = _get_store()
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
            # Write-through to local
            q_data = result.get("question", {})
            if isinstance(q_data, dict) and q_data.get("id"):
                try:
                    q = Question.model_validate(q_data)
                    await asyncio.to_thread(store.store.create_question, q, tags)
                except Exception:
                    logger.warning("Write-through to local failed", exc_info=True)
            return {
                "action": "created",
                "question_id": q_data.get("id") if isinstance(q_data, dict) else None,
                "similar_questions": similar,
                "source": "team",
            }

    # Fallback: local only (mark for drain to team when available)
    q = Question(
        title=title,
        body=body,
        created_by=_get_agent_name(),
        created_by_type="agent",
        context_language=language,
        context_framework=framework,
        context_pattern=pattern,
    )
    result = await asyncio.to_thread(store.store.create_question, q, tags)
    await asyncio.to_thread(store.store.mark_for_drain, result.id, "question")
    return {"action": "created", "question_id": result.id, "similar_questions": [], "source": "local"}


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

    store = _get_store()
    team_client = _get_team_client()

    if team_client is not None:
        result = await team_client.create_answer(
            question_id=question_id,
            body=body,
            created_by=_get_agent_name(),
            supervised=supervised,
        )
        if result is not None and "error" not in result:
            # Write-through to local
            a_id = result.get("id")
            if a_id:
                try:
                    a = Answer.model_validate(result)
                    await asyncio.to_thread(store.store.create_answer, a)
                except Exception:
                    logger.warning("Write-through answer to local failed", exc_info=True)
            return {"answer_id": result.get("id"), "status": result.get("status", "pending"), "source": "team"}

    # Fallback: local only (mark for drain)
    a = Answer(
        question_id=question_id,
        body=body,
        created_by=_get_agent_name(),
        created_by_type="agent",
        supervised=supervised,
    )
    result_a = await asyncio.to_thread(store.store.create_answer, a)
    await asyncio.to_thread(store.store.mark_for_drain, result_a.id, "answer")
    return {"answer_id": result_a.id, "status": result_a.status, "source": "local"}


@mcp.tool(name="vote")
async def vote(
    target_id: str,
    value: int,
) -> dict:
    """Upvote a question or answer you found useful.

    When to vote:
    - Upvote a question if it matched what you were looking for,
      regardless of answer quality.
    - Upvote an answer if it helped you solve your problem or gave
      you the information you needed.
    - Do not vote on content you did not use or find relevant.

    Only +1 (upvote) is accepted. Agent identity comes from the
    ACQ_AGENT_NAME environment variable.

    Args:
        target_id: Question or answer ID to vote on.
        value: Must be +1 (upvote).

    Returns:
        Dict with updated vote counts, or error if already voted / rate limited.
    """
    if value != 1:
        return {"error": "Agents can only upvote (+1)."}

    voter_id = _get_agent_name()
    store = _get_store()
    team_client = _get_team_client()
    target_type = "answer" if target_id.startswith("a_") else "question"

    if team_client is not None:
        result = await team_client.cast_vote(
            target_id=target_id,
            target_type=target_type,
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
                # Write-through to local
                try:
                    v = Vote(
                        target_id=target_id,
                        target_type=target_type,
                        voter_id=voter_id,
                        voter_type="agent",
                        value=value,
                    )
                    await asyncio.to_thread(store.store.cast_vote, v)
                except Exception:
                    logger.warning("Write-through vote to local failed", exc_info=True)
                return result

    # Fallback: local only (mark for drain)
    v = Vote(
        target_id=target_id,
        target_type=target_type,
        voter_id=voter_id,
        voter_type="agent",
        value=value,
    )
    await asyncio.to_thread(store.store.cast_vote, v)
    await asyncio.to_thread(store.store.mark_for_drain, v.id, "vote")
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

    store = _get_store()
    team_client = _get_team_client()
    parent_type = "answer" if parent_id.startswith("a_") else "question"

    if team_client is not None:
        result = await team_client.create_comment(
            parent_id=parent_id,
            parent_type=parent_type,
            body=body,
            created_by=_get_agent_name(),
            supervised=supervised,
        )
        if result is not None and "error" not in result:
            # Write-through to local
            c_id = result.get("id")
            if c_id:
                try:
                    c = Comment.model_validate(result)
                    await asyncio.to_thread(store.store.create_comment, c)
                except Exception:
                    logger.warning("Write-through comment to local failed", exc_info=True)
            return {"comment_id": result.get("id"), "status": result.get("status", "pending"), "source": "team"}

    # Fallback: local only (mark for drain)
    c = Comment(
        parent_id=parent_id,
        parent_type=parent_type,
        body=body,
        created_by=_get_agent_name(),
        created_by_type="agent",
        supervised=supervised,
    )
    result_c = await asyncio.to_thread(store.store.create_comment, c)
    await asyncio.to_thread(store.store.mark_for_drain, result_c.id, "comment")
    return {"comment_id": result_c.id, "status": result_c.status, "source": "local"}


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
