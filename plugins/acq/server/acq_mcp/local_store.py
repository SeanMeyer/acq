"""Local SQLite Q&A store for acq.

Thin wrapper around :class:`acq_shared.sqlite_store.SqliteStore` that adds
team-API drain/pull methods. All storage operations are delegated to the
underlying SqliteStore instance.

Content is drained to the team API on server startup when a connection is
available, and new content is pulled from the team API periodically.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from acq_shared.sqlite_store import SqliteStore

if TYPE_CHECKING:
    from .team_client import TeamClient

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".acq" / "local.db"


class LocalStore:
    """SQLite-backed local Q&A store wrapping :class:`SqliteStore`.

    Holds a single persistent connection for the lifetime of the instance.
    Thread-safe: a lock serialises all connection access so the store
    can be shared across asyncio.to_thread() executor threads.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._closed = False
        # check_same_thread=False allows use from asyncio.to_thread() executor threads.
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._store = SqliteStore(self._conn)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def store(self) -> SqliteStore:
        """The underlying SqliteStore — used by server.py for direct access."""
        return self._store

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("LocalStore is closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()

    def __enter__(self) -> LocalStore:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Convenience delegates (used by drain and legacy callers)
    # ------------------------------------------------------------------

    def create_question(
        self,
        title: str,
        body: str,
        created_by: str,
        tags: list[str],
        language: str | None = None,
        framework: str | None = None,
        pattern: str | None = None,
    ):
        """Create a question (legacy convenience wrapper for drain)."""
        from acq_shared.models import Question

        q = Question(
            title=title,
            body=body,
            created_by=created_by,
            created_by_type="agent",
            context_language=language,
            context_framework=framework,
            context_pattern=pattern,
        )
        with self._lock:
            self._check_open()
            self._store.create_question(q, tags)
        return q

    def create_answer(
        self,
        question_id: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ):
        """Create an answer (legacy convenience wrapper for drain)."""
        from acq_shared.models import Answer

        a = Answer(
            question_id=question_id,
            body=body,
            created_by=created_by,
            created_by_type="agent",
            supervised=supervised,
        )
        with self._lock:
            self._check_open()
            self._store.create_answer(a)
        return a

    def cast_vote(
        self,
        target_id: str,
        target_type: str,
        voter_id: str,
        voter_type: str,
        value: int,
    ):
        """Cast a vote (legacy convenience wrapper for drain)."""
        from acq_shared.models import Vote

        v = Vote(
            target_id=target_id,
            target_type=target_type,  # type: ignore[arg-type]
            voter_id=voter_id,
            voter_type=voter_type,  # type: ignore[arg-type]
            value=value,  # type: ignore[arg-type]
        )
        with self._lock:
            self._check_open()
            self._store.cast_vote(v)
        return v

    def create_comment(
        self,
        parent_id: str,
        parent_type: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ):
        """Create a comment (legacy convenience wrapper for drain)."""
        from acq_shared.models import Comment

        c = Comment(
            parent_id=parent_id,
            parent_type=parent_type,  # type: ignore[arg-type]
            body=body,
            created_by=created_by,
            created_by_type="agent",
            supervised=supervised,
        )
        with self._lock:
            self._check_open()
            self._store.create_comment(c)
        return c

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        language: str | None = None,
        framework: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """FTS5 search on local store. Delegates to SqliteStore."""
        with self._lock:
            self._check_open()
            return self._store.search(
                query,
                tags=tags,
                language=language,
                framework=framework,
                limit=limit,
            )

    def get_status(self) -> dict:
        with self._lock:
            self._check_open()
            return self._store.get_status()

    def all_questions(self):
        from acq_shared.models import Question

        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM questions").fetchall()
        return [Question.model_validate_json(r[0]) for r in rows]

    def all_answers(self):
        from acq_shared.models import Answer

        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM answers").fetchall()
        return [Answer.model_validate_json(r[0]) for r in rows]

    def all_votes(self):
        from acq_shared.models import Vote

        with self._lock:
            self._check_open()
            rows = self._conn.execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM votes"
            ).fetchall()
        return [
            Vote(
                id=r[0],
                target_id=r[1],
                target_type=r[2],
                voter_id=r[3],
                voter_type=r[4],
                value=r[5],
                created_at=r[6],
            )
            for r in rows
        ]

    def all_comments(self):
        from acq_shared.models import Comment

        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM comments").fetchall()
        return [Comment.model_validate_json(r[0]) for r in rows]

    def delete_question(self, question_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
                self._conn.execute("DELETE FROM search_index WHERE question_id = ?", (question_id,))

    def delete_answer(self, answer_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
                self._conn.execute("DELETE FROM search_index WHERE entity_id = ?", (answer_id,))

    def delete_vote(self, vote_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM votes WHERE id = ?", (vote_id,))

    def delete_comment(self, comment_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))

    # ------------------------------------------------------------------
    # Team sync
    # ------------------------------------------------------------------

    async def drain_to_team(self, team_client: TeamClient) -> int:
        """Push locally-created content to the team API.

        Only drains items in the pending_drain queue — content pulled from the
        team via bulk_upsert is never drained back. Returns the number of items
        successfully drained.
        """
        with self._lock:
            self._check_open()
            pending = self._store.get_pending_drain()

        if not pending:
            return 0

        drained = 0
        from acq_shared.models import Answer, Comment, Question

        for item in pending:
            eid, etype = item["entity_id"], item["entity_type"]
            try:
                if etype == "question":
                    row = self._conn.execute("SELECT data FROM questions WHERE id = ?", (eid,)).fetchone()
                    if not row:
                        self._store.clear_drain(eid)
                        continue
                    q = Question.model_validate_json(row[0])
                    tags = self._get_tag_names_for_question_unlocked(q.id)
                    result = await team_client.create_question(
                        title=q.title,
                        body=q.body,
                        created_by=q.created_by,
                        tags=tags,
                        language=q.context_language,
                        framework=q.context_framework,
                        pattern=q.context_pattern,
                        force_create=True,
                    )
                    if result.ok:
                        self._store.clear_drain(eid)
                        drained += 1

                elif etype == "answer":
                    row = self._conn.execute("SELECT data FROM answers WHERE id = ?", (eid,)).fetchone()
                    if not row:
                        self._store.clear_drain(eid)
                        continue
                    a = Answer.model_validate_json(row[0])
                    result = await team_client.create_answer(
                        question_id=a.question_id,
                        body=a.body,
                        created_by=a.created_by,
                        supervised=a.supervised,
                    )
                    if result.ok:
                        self._store.clear_drain(eid)
                        drained += 1

                elif etype == "vote":
                    row = self._conn.execute(
                        "SELECT target_id, target_type, voter_id, value FROM votes WHERE id = ?", (eid,)
                    ).fetchone()
                    if not row:
                        self._store.clear_drain(eid)
                        continue
                    result = await team_client.cast_vote(
                        target_id=row[0],
                        target_type=row[1],
                        value=row[3],
                        voter_id=row[2],
                    )
                    if result.ok:
                        self._store.clear_drain(eid)
                        drained += 1

                elif etype == "comment":
                    row = self._conn.execute("SELECT data FROM comments WHERE id = ?", (eid,)).fetchone()
                    if not row:
                        self._store.clear_drain(eid)
                        continue
                    c = Comment.model_validate_json(row[0])
                    result = await team_client.create_comment(
                        parent_id=c.parent_id,
                        parent_type=c.parent_type,
                        body=c.body,
                        created_by=c.created_by,
                        supervised=c.supervised,
                    )
                    if result.ok:
                        self._store.clear_drain(eid)
                        drained += 1

            except Exception:
                logger.warning("Failed to drain %s %s to team", etype, eid, exc_info=True)

        return drained

    async def pull_from_team(self, team_client: TeamClient, since: str | None = None) -> int:
        """Pull content from team API and upsert into local store.

        Returns the number of items upserted.
        """
        result = await team_client.export_since(since=since)
        if not result.ok:
            return 0
        with self._lock:
            self._check_open()
            return self._store.bulk_upsert(result.data)

    def _get_tag_names_for_question_unlocked(self, question_id: str) -> list[str]:
        """Read tag names without acquiring the lock (caller must hold it or be safe)."""
        rows = self._conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN question_tags qt ON qt.tag_id = t.id
            WHERE qt.question_id = ?
            """,
            (question_id,),
        ).fetchall()
        return [r[0] for r in rows]
