"""Local SQLite Q&A store for acq.

Stores questions, answers, votes, and comments locally as a fallback buffer
when the team API is unreachable. Content is drained to the team API on
server startup when a connection is available.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from acq_shared.models import Answer, Comment, Question, Tag, Vote
from acq_shared.schema import create_tables

if TYPE_CHECKING:
    from .team_client import TeamClient

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".acq" / "local.db"


class LocalStore:
    """SQLite-backed local Q&A store.

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
        create_tables(self._conn)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("LocalStore is closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "LocalStore":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def create_question(
        self,
        title: str,
        body: str,
        created_by: str,
        tags: list[str],
        language: str | None = None,
        framework: str | None = None,
        pattern: str | None = None,
    ) -> Question:
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
            with self._conn:
                self._conn.execute(
                    "INSERT INTO questions (id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        q.id,
                        q.model_dump_json(),
                        q.status,
                        q.created_at.isoformat(),
                        q.updated_at.isoformat(),
                    ),
                )
                for tag_name in tags:
                    normalized = tag_name.strip().lower()
                    if not normalized:
                        continue
                    # Upsert tag, incrementing usage_count.
                    row = self._conn.execute(
                        "SELECT id FROM tags WHERE name = ?", (normalized,)
                    ).fetchone()
                    if row:
                        tag_id = row[0]
                        self._conn.execute(
                            "UPDATE tags SET usage_count = usage_count + 1 WHERE id = ?",
                            (tag_id,),
                        )
                    else:
                        tag = Tag(name=normalized)
                        tag_id = tag.id
                        self._conn.execute(
                            "INSERT INTO tags (id, name, usage_count) VALUES (?, ?, ?)",
                            (tag_id, normalized, 1),
                        )
                    self._conn.execute(
                        "INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)",
                        (q.id, tag_id),
                    )
                self._conn.execute(
                    "INSERT INTO search_index (entity_id, entity_type, question_id, title, body) VALUES (?, ?, ?, ?, ?)",
                    (q.id, "question", q.id, title, body),
                )
        return q

    def create_answer(
        self,
        question_id: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> Answer:
        a = Answer(
            question_id=question_id,
            body=body,
            created_by=created_by,
            created_by_type="agent",
            supervised=supervised,
        )
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO answers (id, question_id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        a.id,
                        a.question_id,
                        a.model_dump_json(),
                        a.status,
                        a.created_at.isoformat(),
                        a.updated_at.isoformat(),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO search_index (entity_id, entity_type, question_id, title, body) VALUES (?, ?, ?, ?, ?)",
                    (a.id, "answer", question_id, "", body),
                )
        return a

    def cast_vote(
        self,
        target_id: str,
        target_type: str,
        voter_id: str,
        voter_type: str,
        value: int,
    ) -> Vote:
        v = Vote(
            target_id=target_id,
            target_type=target_type,  # type: ignore[arg-type]
            voter_id=voter_id,
            voter_type=voter_type,  # type: ignore[arg-type]
            value=value,  # type: ignore[arg-type]
        )
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO votes (id, target_id, target_type, voter_id, voter_type, value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        v.id,
                        v.target_id,
                        v.target_type,
                        v.voter_id,
                        v.voter_type,
                        v.value,
                        v.created_at.isoformat(),
                    ),
                )
        return v

    def create_comment(
        self,
        parent_id: str,
        parent_type: str,
        body: str,
        created_by: str,
        supervised: bool = False,
    ) -> Comment:
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
            with self._conn:
                self._conn.execute(
                    "INSERT INTO comments (id, parent_id, parent_type, data, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        c.id,
                        c.parent_id,
                        c.parent_type,
                        c.model_dump_json(),
                        c.status,
                        c.created_at.isoformat(),
                    ),
                )
        return c

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        language: str | None = None,
        framework: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """FTS5 search on local store. Returns question dicts with top answers."""
        results: list[dict] = []
        with self._lock:
            self._check_open()
            if query.strip():
                # FTS5 MATCH defaults to AND — too strict when users
                # search with different vocabulary than the author.
                # Split into OR so any matching word surfaces results.
                words = query.strip().split()
                fts_query = " OR ".join(w for w in words if w)
                try:
                    rows = self._conn.execute(
                        """
                        SELECT DISTINCT question_id
                        FROM search_index
                        WHERE search_index MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (fts_query, limit * 2),
                    ).fetchall()
                    question_ids = [r[0] for r in rows]
                except sqlite3.OperationalError:
                    question_ids = []
            else:
                question_ids = []

            seen: set[str] = set()
            for qid in question_ids:
                if qid in seen:
                    continue
                seen.add(qid)
                row = self._conn.execute(
                    "SELECT data FROM questions WHERE id = ?", (qid,)
                ).fetchone()
                if not row:
                    continue
                q = Question.model_validate_json(row[0])
                if language and q.context_language and q.context_language != language:
                    continue
                if framework and q.context_framework and q.context_framework != framework:
                    continue
                answers = self._get_answers_for_question(qid)
                results.append(_question_to_result(q, answers))
                if len(results) >= limit:
                    break

        return results

    def _get_answers_for_question(self, question_id: str) -> list[Answer]:
        rows = self._conn.execute(
            "SELECT data FROM answers WHERE question_id = ? ORDER BY created_at",
            (question_id,),
        ).fetchall()
        return [Answer.model_validate_json(r[0]) for r in rows]

    def get_status(self) -> dict:
        with self._lock:
            self._check_open()
            q_count = self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            a_count = self._conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
            tag_count = self._conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            vote_count = self._conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
        return {
            "questions": q_count,
            "answers": a_count,
            "tags": tag_count,
            "votes": vote_count,
        }

    def all_questions(self) -> list[Question]:
        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM questions").fetchall()
        return [Question.model_validate_json(r[0]) for r in rows]

    def all_answers(self) -> list[Answer]:
        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM answers").fetchall()
        return [Answer.model_validate_json(r[0]) for r in rows]

    def all_votes(self) -> list[Vote]:
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

    def all_comments(self) -> list[Comment]:
        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT data FROM comments").fetchall()
        return [Comment.model_validate_json(r[0]) for r in rows]

    def delete_question(self, question_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
                self._conn.execute(
                    "DELETE FROM search_index WHERE question_id = ?", (question_id,)
                )

    def delete_answer(self, answer_id: str) -> None:
        with self._lock:
            self._check_open()
            with self._conn:
                self._conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
                self._conn.execute(
                    "DELETE FROM search_index WHERE entity_id = ?", (answer_id,)
                )

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

    async def drain_to_team(self, team_client: "TeamClient") -> int:
        """POST all local content to the team API, deleting on success.

        Returns the number of items successfully drained.
        """
        drained = 0

        # Drain answers before questions so FK cascade deletion doesn't remove them first.
        for a in self.all_answers():
            try:
                result = await team_client.create_answer(
                    question_id=a.question_id,
                    body=a.body,
                    created_by=a.created_by,
                    supervised=a.supervised,
                )
                if result is not None:
                    self.delete_answer(a.id)
                    drained += 1
            except Exception:
                logger.warning("Failed to drain answer %s to team", a.id, exc_info=True)

        for q in self.all_questions():
            try:
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
                if result is not None:
                    self.delete_question(q.id)
                    drained += 1
            except Exception:
                logger.warning("Failed to drain question %s to team", q.id, exc_info=True)

        for v in self.all_votes():
            try:
                result = await team_client.cast_vote(
                    target_id=v.target_id,
                    value=v.value,
                    voter_id=v.voter_id,
                )
                if result is not None:
                    self.delete_vote(v.id)
                    drained += 1
            except Exception:
                logger.warning("Failed to drain vote %s to team", v.id, exc_info=True)

        for c in self.all_comments():
            try:
                result = await team_client.create_comment(
                    parent_id=c.parent_id,
                    body=c.body,
                    created_by=c.created_by,
                    supervised=c.supervised,
                )
                if result is not None:
                    self.delete_comment(c.id)
                    drained += 1
            except Exception:
                logger.warning("Failed to drain comment %s to team", c.id, exc_info=True)

        return drained

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


def _question_to_result(q: Question, answers: list[Answer]) -> dict:
    approved = [a for a in answers if a.status == "approved"]
    top_answer = approved[0] if approved else (answers[0] if answers else None)
    return {
        "id": q.id,
        "title": q.title,
        "body": q.body,
        "status": q.status,
        "created_by": q.created_by,
        "tags": [],
        "context_language": q.context_language,
        "context_framework": q.context_framework,
        "top_answer": top_answer.model_dump(mode="json") if top_answer else None,
        "answer_count": len(answers),
        "vote_score": (
            q.agent_upvotes
            - q.agent_downvotes
            + 5 * (q.human_upvotes - q.human_downvotes)
        ),
    }
