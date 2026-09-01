"""PostgresStore — Postgres-backed Store implementation.

Mirrors SqliteStore method-for-method but uses psycopg2, ``acq.`` schema
prefix, and tsvector columns for full-text search instead of FTS5.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg2
import psycopg2.extensions

from acq_shared.models import Answer, Comment, EditHistory, Question, Tag, Vote
from acq_shared.postgres_schema import create_tables
from acq_shared.scoring import (
    DUPLICATE_THRESHOLD,
    duplicate_similarity,
    rank_answers,
    search_score,
    text_relevance_score,
)

# Mirrors the SQLite store: bound the rows pulled from full-text search before
# absolute scoring, since ORing a title's terms can match a large slice of a
# mature corpus and only the best three candidates are returned.
_CANDIDATE_LIMIT = 50


def _normalized_rank(raw_rank: float, min_rank: float, max_rank: float) -> float:
    """Scale a ts_rank into 0-1, where higher is more relevant.

    When every match has the same rank there is no spread to scale against.
    In that case all matches are equally relevant and must map to 1.0, not
    0.0: ``search_score`` multiplies by text relevance, so returning 0.0
    would zero out every result and discard the vote, tag, and context
    signals entirely. That also covers the common single-result search,
    where min and max are necessarily equal.
    """
    if max_rank == min_rank:
        return 1.0
    return (raw_rank - min_rank) / (max_rank - min_rank)


class PostgresStore:
    """Postgres-backed store implementing the Store protocol.

    Constructor takes a psycopg2 connection and calls ``create_tables()``
    to ensure the ``acq`` schema exists.
    """

    def __init__(self, conn, *, create_schema: bool = True, connect: Any = None) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._connect = connect  # Optional callable that returns a fresh connection
        if create_schema:
            create_tables(conn)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _reconnect(self) -> None:
        """Replace the connection using the connect factory."""
        if self._connect is None:
            raise RuntimeError("no connect factory configured")
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = self._connect()

    def _execute(self, sql: str, params: tuple = ()) -> Any:
        with self._lock:
            # Captured *before* executing. If no transaction is open yet then
            # this statement is the first of a unit of work, so replaying it on
            # a fresh connection loses nothing. Mid-transaction we must never
            # replay: the caller's earlier statements are uncommitted, a new
            # connection starts a new transaction without them, and the
            # caller's later commit() would persist a partial write.
            at_statement_boundary = (
                self._connect is not None
                and self._conn.closed == 0
                and self._conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
            )
            try:
                cur = self._conn.cursor()
                cur.execute(sql, params)
                return cur
            except psycopg2.Error:
                # Retry only a genuinely dead connection (dropped socket,
                # restarted server, expired credential), which psycopg2 marks
                # by setting `closed` non-zero. Everything else — deadlock,
                # serialization failure, statement timeout, lock timeout,
                # constraint violation — leaves a live connection whose
                # transaction is merely aborted. Note that several of those are
                # OperationalError subclasses, so the exception type alone is
                # not a safe signal.
                if at_statement_boundary and self._conn.closed != 0:
                    self._reconnect()
                    cur = self._conn.cursor()
                    cur.execute(sql, params)
                    return cur
                # Postgres rejects every further statement on a connection
                # whose transaction is aborted, so roll back to keep it usable,
                # then let the caller see the original error.
                try:
                    self._conn.rollback()
                except psycopg2.Error:
                    pass
                raise

    def _execute_returning(self, sql: str, params: tuple = ()) -> Any:
        cur = self._execute(sql, params)
        return cur

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, username: str, password_hash: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._execute(
            "INSERT INTO acq.users (username, password_hash, created_at) VALUES (%s, %s, %s)",
            (username, password_hash, now),
        )
        self._conn.commit()

    def get_user(self, username: str) -> dict[str, str] | None:
        cur = self._execute(
            "SELECT username, password_hash, created_at FROM acq.users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"username": row[0], "password_hash": row[1], "created_at": str(row[2])}

    # ------------------------------------------------------------------
    # Agent keys
    # ------------------------------------------------------------------

    def create_agent_key(self, api_key: str, agent_name: str, github_username: str) -> dict:
        now = datetime.now(UTC).isoformat()
        self._execute(
            "INSERT INTO acq.agent_keys (api_key, agent_name, github_username, created_at) VALUES (%s, %s, %s, %s)",
            (api_key, agent_name, github_username, now),
        )
        self._conn.commit()
        return {"api_key": api_key, "agent_name": agent_name, "github_username": github_username, "created_at": now}

    def get_agent_key(self, api_key: str) -> dict | None:
        cur = self._execute(
            "SELECT api_key, agent_name, github_username, created_at FROM acq.agent_keys WHERE api_key = %s",
            (api_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

    def get_agent_key_by_github(self, github_username: str) -> dict | None:
        cur = self._execute(
            "SELECT api_key, agent_name, github_username, created_at FROM acq.agent_keys WHERE github_username = %s",
            (github_username,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def get_or_create_tag(self, name: str) -> Tag:
        tag = self._get_or_create_tag(name)
        self._conn.commit()
        return tag

    def _get_or_create_tag(self, name: str) -> Tag:
        """Resolve a tag, creating it if new, without committing.

        Kept separate from the public method so a caller that is midway
        through a larger unit of work can resolve tags without flushing its
        own half-finished writes.
        """
        tag = Tag(name=name)
        cur = self._execute(
            "SELECT id, name, description, usage_count FROM acq.tags WHERE name = %s",
            (tag.name,),
        )
        row = cur.fetchone()
        if row is not None:
            return Tag(id=row[0], name=row[1], description=row[2], usage_count=row[3])
        self._execute(
            "INSERT INTO acq.tags (id, name, description, usage_count) VALUES (%s, %s, %s, %s)",
            (tag.id, tag.name, tag.description, tag.usage_count),
        )
        return tag

    def merge_tags(self, source_id: str, target_id: str) -> None:
        # Collect affected questions before the merge so we can refresh tsvectors.
        cur = self._execute(
            "SELECT question_id FROM acq.question_tags WHERE tag_id = %s OR tag_id = %s",
            (source_id, target_id),
        )
        affected_qids = {r[0] for r in cur.fetchall()}

        self._execute(
            """
            UPDATE acq.question_tags SET tag_id = %s
            WHERE tag_id = %s
              AND question_id NOT IN (
                  SELECT question_id FROM acq.question_tags WHERE tag_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        self._execute("DELETE FROM acq.question_tags WHERE tag_id = %s", (source_id,))
        self._execute("DELETE FROM acq.tags WHERE id = %s", (source_id,))
        cur = self._execute("SELECT COUNT(*) FROM acq.question_tags WHERE tag_id = %s", (target_id,))
        row = cur.fetchone()
        self._execute("UPDATE acq.tags SET usage_count = %s WHERE id = %s", (row[0], target_id))

        # Refresh tsvectors for affected questions.
        for qid in affected_qids:
            self._refresh_question_tsvector(qid)

        self._conn.commit()

    def list_tags(self, q: str | None = None) -> list[Tag]:
        if q:
            cur = self._execute(
                "SELECT id, name, description, usage_count FROM acq.tags WHERE name LIKE %s",
                (f"%{q}%",),
            )
        else:
            cur = self._execute("SELECT id, name, description, usage_count FROM acq.tags ORDER BY usage_count DESC")
        rows = cur.fetchall()
        return [Tag(id=r[0], name=r[1], description=r[2], usage_count=r[3]) for r in rows]

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def create_question(self, question: Question, tag_names: list[str]) -> Question:
        # Agent-authored questions enter the review queue; human-authored ones
        # and those asked under supervision go live at once. Mirrors what
        # create_answer does with answer.supervised. This cannot live in a
        # model_post_init hook: that hook re-runs on every
        # model_validate_json, so it would resurrect a rejected question on
        # every read.
        if question.status == "pending" and (question.created_by_type == "human" or question.supervised):
            question = question.model_copy(update={"status": "open"})
        self._execute(
            "INSERT INTO acq.questions (id, data, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            (
                question.id,
                question.model_dump_json(),
                question.status,
                question.created_at.isoformat(),
                question.updated_at.isoformat(),
            ),
        )
        tags = [self._get_or_create_tag(name) for name in tag_names]
        for tag in tags:
            self._execute(
                "INSERT INTO acq.question_tags (question_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (question.id, tag.id),
            )
            self._execute("UPDATE acq.tags SET usage_count = usage_count + 1 WHERE id = %s", (tag.id,))
        # Update tsvector with title + body + tag names.
        tag_text = " ".join(t.name for t in tags)
        self._execute(
            "UPDATE acq.questions SET search_vector ="
            " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
            (question.title, question.body, tag_text, question.id),
        )
        self._conn.commit()
        return question

    def get_question(self, question_id: str) -> Question | None:
        cur = self._execute("SELECT data FROM acq.questions WHERE id = %s", (question_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Question.model_validate_json(row[0])

    def _record_edit(
        self,
        target_id: str,
        target_type: Literal["question", "question_title", "answer", "comment"],
        previous_body: str,
        new_body: str,
        edited_by: str,
        edited_by_type: Literal["agent", "human"],
    ) -> None:
        """Append one append-only edit_history row. The caller commits."""
        history = EditHistory(
            target_id=target_id,
            target_type=target_type,
            previous_body=previous_body,
            new_body=new_body,
            edited_by=edited_by,
            edited_by_type=edited_by_type,
        )
        self._execute(
            "INSERT INTO acq.edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                history.id,
                history.target_id,
                history.target_type,
                history.previous_body,
                history.new_body,
                history.edited_by,
                history.edited_by_type,
                history.edited_at.isoformat(),
            ),
        )

    def _set_question_tags(self, question_id: str, tag_names: list[str]) -> None:
        """Replace a question's tag set with *tag_names*. The caller commits.

        usage_count is recomputed from question_tags rather than incremented
        and decremented, so repeated tag edits cannot make it drift.
        """
        desired = {self._get_or_create_tag(name).id for name in tag_names}
        cur = self._execute("SELECT tag_id FROM acq.question_tags WHERE question_id = %s", (question_id,))
        current = {r[0] for r in cur.fetchall()}
        for tag_id in current - desired:
            self._execute(
                "DELETE FROM acq.question_tags WHERE question_id = %s AND tag_id = %s",
                (question_id, tag_id),
            )
        for tag_id in desired - current:
            self._execute(
                "INSERT INTO acq.question_tags (question_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (question_id, tag_id),
            )
        for tag_id in current | desired:
            count = self._execute("SELECT COUNT(*) FROM acq.question_tags WHERE tag_id = %s", (tag_id,)).fetchone()[0]
            self._execute("UPDATE acq.tags SET usage_count = %s WHERE id = %s", (count, tag_id))

    def edit_question(
        self,
        question_id: str,
        new_body: str | None,
        edited_by: str,
        edited_by_type: Literal["agent", "human"],
        new_title: str | None = None,
        new_tags: list[str] | None = None,
    ) -> Question | None:
        """Update a question's body, title, and/or tag set.

        Every field is optional; ``None`` means "leave unchanged", so a caller
        can retitle a question without resubmitting its body. Body and title
        changes are appended to edit_history under the target types
        ``question`` and ``question_title``. Tag changes are not audited,
        matching the MVP decision to record body edits only.
        """
        q = self.get_question(question_id)
        if q is None:
            return None

        updates: dict[str, Any] = {}
        if new_body is not None and new_body != q.body:
            self._record_edit(question_id, "question", q.body, new_body, edited_by, edited_by_type)
            updates["body"] = new_body
        if new_title is not None and new_title != q.title:
            self._record_edit(question_id, "question_title", q.title, new_title, edited_by, edited_by_type)
            updates["title"] = new_title
        if new_tags is not None:
            self._set_question_tags(question_id, new_tags)
        if not updates and new_tags is None:
            return q

        now = datetime.now(UTC)
        updated = q.model_copy(update={**updates, "updated_at": now})
        self._execute(
            "UPDATE acq.questions SET data = %s, updated_at = %s WHERE id = %s",
            (updated.model_dump_json(), now.isoformat(), question_id),
        )
        # Refresh tsvector with title + body + tag names.
        tag_text = " ".join(sorted(self._get_question_tag_names(question_id)))
        self._execute(
            "UPDATE acq.questions SET search_vector ="
            " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
            (updated.title, updated.body, tag_text, question_id),
        )
        self._conn.commit()
        return updated

    def pin_answer(self, question_id: str, answer_id: str) -> Question | None:
        q = self.get_question(question_id)
        if q is None:
            return None
        updated = q.model_copy(update={"pinned_answer_id": answer_id})
        self._execute(
            "UPDATE acq.questions SET data = %s WHERE id = %s",
            (updated.model_dump_json(), question_id),
        )
        self._conn.commit()
        return updated

    def unpin_answer(self, question_id: str) -> Question | None:
        q = self.get_question(question_id)
        if q is None:
            return None
        updated = q.model_copy(update={"pinned_answer_id": None})
        self._execute(
            "UPDATE acq.questions SET data = %s WHERE id = %s",
            (updated.model_dump_json(), question_id),
        )
        self._conn.commit()
        return updated

    def get_question_history(self, question_id: str) -> list[EditHistory]:
        cur = self._execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM acq.edit_history WHERE target_id = %s AND target_type IN ('question', 'question_title') ORDER BY edited_at ASC",
            (question_id,),
        )
        rows = cur.fetchall()
        return [_row_to_edit_history(r) for r in rows]

    def _write_question_status(self, q: Question, status: str) -> None:
        now = datetime.now(UTC)
        updated = q.model_copy(update={"status": status, "updated_at": now})
        self._execute(
            "UPDATE acq.questions SET data = %s, status = %s, updated_at = %s WHERE id = %s",
            (updated.model_dump_json(), status, now.isoformat(), q.id),
        )
        self._conn.commit()

    def list_questions(
        self,
        status: str | None = None,
        tag: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        where_clauses: list[str] = []
        params: list[str | int] = []
        join = ""

        if status is not None:
            where_clauses.append("q.status = %s")
            params.append(status)
        else:
            # Questions awaiting review and soft-deleted ones are both hidden
            # unless asked for by name; status='pending' is how the curation
            # UI lists the review queue.
            where_clauses.append("q.status NOT IN ('deleted', 'pending')")
        if tag is not None:
            join = " JOIN acq.question_tags qt ON q.id = qt.question_id JOIN acq.tags t ON qt.tag_id = t.id"
            where_clauses.append("t.name = %s")
            params.append(tag)

        where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_select = "COUNT(DISTINCT q.id)" if tag is not None else "COUNT(*)"
        total = self._execute(f"SELECT {count_select} FROM acq.questions q{join}{where}", tuple(params)).fetchone()[0]

        rows = self._execute(
            f"SELECT q.data FROM acq.questions q{join}{where} ORDER BY q.created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()

        results: list[dict] = []
        for (data_json,) in rows:
            q = Question.model_validate_json(data_json)
            tag_names = self._get_question_tag_names(q.id)
            tags = [{"name": n} for n in sorted(tag_names)]
            answer_count = self._execute(
                "SELECT COUNT(*) FROM acq.answers WHERE question_id = %s AND status IN ('approved', 'pending')",
                (q.id,),
            ).fetchone()[0]
            results.append({"question": q.model_dump(mode="json"), "tags": tags, "answer_count": answer_count})
        return results, total

    # ------------------------------------------------------------------
    # Answers
    # ------------------------------------------------------------------

    def create_answer(self, answer: Answer) -> Answer:
        if answer.supervised:
            answer = answer.model_copy(update={"status": "approved"})
        self._execute(
            "INSERT INTO acq.answers (id, question_id, data, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                answer.id,
                answer.question_id,
                answer.model_dump_json(),
                answer.status,
                answer.created_at.isoformat(),
                answer.updated_at.isoformat(),
            ),
        )
        # Update tsvector
        self._execute(
            "UPDATE acq.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
            (answer.body, answer.id),
        )
        self._conn.commit()
        return answer

    def get_answer(self, answer_id: str) -> Answer | None:
        cur = self._execute("SELECT data FROM acq.answers WHERE id = %s", (answer_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Answer.model_validate_json(row[0])

    def edit_answer(
        self, answer_id: str, new_body: str, edited_by: str, edited_by_type: Literal["agent", "human"]
    ) -> Answer | None:
        a = self.get_answer(answer_id)
        if a is None:
            return None
        history = EditHistory(
            target_id=answer_id,
            target_type="answer",
            previous_body=a.body,
            new_body=new_body,
            edited_by=edited_by,
            edited_by_type=edited_by_type,
        )
        self._execute(
            "INSERT INTO acq.edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                history.id,
                history.target_id,
                history.target_type,
                history.previous_body,
                history.new_body,
                history.edited_by,
                history.edited_by_type,
                history.edited_at.isoformat(),
            ),
        )
        now = datetime.now(UTC)
        updated = a.model_copy(update={"body": new_body, "updated_at": now})
        self._execute(
            "UPDATE acq.answers SET data = %s, updated_at = %s WHERE id = %s",
            (updated.model_dump_json(), now.isoformat(), answer_id),
        )
        # Refresh tsvector
        self._execute(
            "UPDATE acq.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
            (updated.body, answer_id),
        )
        self._conn.commit()
        return updated

    def get_answer_history(self, answer_id: str) -> list[EditHistory]:
        cur = self._execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM acq.edit_history WHERE target_id = %s AND target_type = 'answer' ORDER BY edited_at ASC",
            (answer_id,),
        )
        rows = cur.fetchall()
        return [_row_to_edit_history(r) for r in rows]

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def create_comment(self, comment: Comment) -> Comment:
        self._execute(
            "INSERT INTO acq.comments (id, parent_id, parent_type, data, status, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                comment.id,
                comment.parent_id,
                comment.parent_type,
                comment.model_dump_json(),
                comment.status,
                comment.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        return comment

    def get_comment(self, comment_id: str) -> Comment | None:
        cur = self._execute("SELECT data FROM acq.comments WHERE id = %s", (comment_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Comment.model_validate_json(row[0])

    def edit_comment(
        self, comment_id: str, new_body: str, edited_by: str, edited_by_type: Literal["agent", "human"]
    ) -> Comment | None:
        c = self.get_comment(comment_id)
        if c is None:
            return None
        self._record_edit(comment_id, "comment", c.body, new_body, edited_by, edited_by_type)
        updated = c.model_copy(update={"body": new_body})
        self._execute(
            "UPDATE acq.comments SET data = %s WHERE id = %s",
            (updated.model_dump_json(), comment_id),
        )
        self._conn.commit()
        return updated

    def get_comment_history(self, comment_id: str) -> list[EditHistory]:
        cur = self._execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM acq.edit_history WHERE target_id = %s AND target_type = 'comment' ORDER BY edited_at ASC",
            (comment_id,),
        )
        return [_row_to_edit_history(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Votes
    # ------------------------------------------------------------------

    def cast_vote(self, vote: Vote) -> dict[str, Any]:
        cur = self._execute(
            "SELECT created_at FROM acq.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
            (vote.target_id, vote.voter_id, vote.voter_type),
        )
        existing = cur.fetchone()
        if existing is not None:
            return {"error": "duplicate_vote"}

        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        cur = self._execute(
            "SELECT created_at FROM acq.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s AND created_at >= %s",
            (vote.target_id, vote.voter_id, vote.voter_type, cutoff),
        )
        recent = cur.fetchone()
        if recent is not None:
            return {"error": "rate_limited"}

        try:
            self._execute(
                "INSERT INTO acq.votes (id, target_id, target_type, voter_id, voter_type, value, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    vote.id,
                    vote.target_id,
                    vote.target_type,
                    vote.voter_id,
                    vote.voter_type,
                    vote.value,
                    vote.created_at.isoformat(),
                ),
            )
        except psycopg2.IntegrityError:
            self._conn.rollback()
            return {"error": "duplicate_vote"}

        counts = self._recalculate_vote_counts(vote.target_id, vote.target_type)
        self._conn.commit()
        return counts

    def _recalculate_vote_counts(self, target_id: str, target_type: str) -> dict[str, int]:
        cur = self._execute(
            "SELECT voter_type, value, COUNT(*) FROM acq.votes WHERE target_id = %s GROUP BY voter_type, value",
            (target_id,),
        )
        rows = cur.fetchall()
        counts: dict[str, int] = {
            "agent_upvotes": 0,
            "agent_downvotes": 0,
            "human_upvotes": 0,
            "human_downvotes": 0,
        }
        for voter_type, value, cnt in rows:
            if voter_type == "agent" and value == 1:
                counts["agent_upvotes"] = cnt
            elif voter_type == "agent" and value == -1:
                counts["agent_downvotes"] = cnt
            elif voter_type == "human" and value == 1:
                counts["human_upvotes"] = cnt
            elif voter_type == "human" and value == -1:
                counts["human_downvotes"] = cnt

        if target_type == "question":
            cur = self._execute("SELECT data FROM acq.questions WHERE id = %s", (target_id,))
            data_row = cur.fetchone()
            if data_row:
                q = Question.model_validate_json(data_row[0])
                updated = q.model_copy(update=counts)
                self._execute(
                    "UPDATE acq.questions SET data = %s WHERE id = %s",
                    (updated.model_dump_json(), target_id),
                )
        elif target_type == "answer":
            cur = self._execute("SELECT data FROM acq.answers WHERE id = %s", (target_id,))
            data_row = cur.fetchone()
            if data_row:
                a = Answer.model_validate_json(data_row[0])
                updated = a.model_copy(update=counts)
                self._execute(
                    "UPDATE acq.answers SET data = %s WHERE id = %s",
                    (updated.model_dump_json(), target_id),
                )
        return counts

    def delete_vote(self, target_id: str, voter_id: str, voter_type: str) -> bool:
        cur = self._execute(
            "SELECT target_type FROM acq.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
            (target_id, voter_id, voter_type),
        )
        row = cur.fetchone()
        if row is None:
            return False
        target_type = row[0]
        self._execute(
            "DELETE FROM acq.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
            (target_id, voter_id, voter_type),
        )
        self._recalculate_vote_counts(target_id, target_type)
        self._conn.commit()
        return True

    def get_user_votes(self, voter_id: str, voter_type: str, target_ids: list[str]) -> dict[str, int]:
        if not target_ids:
            return {}
        placeholders = ",".join("%s" for _ in target_ids)
        cur = self._execute(
            f"SELECT target_id, value FROM acq.votes WHERE voter_id = %s AND voter_type = %s AND target_id IN ({placeholders})",
            (voter_id, voter_type, *target_ids),
        )
        return {r[0]: r[1] for r in cur.fetchall()}

    # ------------------------------------------------------------------
    # Moderation
    # ------------------------------------------------------------------

    def approve_content(self, content_id: str) -> bool | None:
        """Make a question, answer, or comment visible, whether pending or rejected.

        Accepting rejected content is what makes rejection reversible, so this
        doubles as the restore path for soft-deleted questions, answers, and
        comments.
        """
        return self._set_content_status(content_id, "approved")

    def reject_content(self, content_id: str) -> bool | None:
        """Hide a question, answer, or comment, whether pending or already live.

        Rejection is the soft-delete mechanism: the row is kept and only its
        status changes, so restoring it later is a status change back.
        """
        return self._set_content_status(content_id, "rejected")

    def _set_content_status(self, content_id: str, new_status: str) -> bool | None:
        """Move a question, answer, or comment to *new_status*.

        Returns None when no such content exists and False when it already has
        that status, which is the distinction the routes turn into 404 versus
        409.
        """
        # Questions are resolved first and separately: their verdict covers the
        # answers filed under them, which the answer/comment loop knows nothing
        # about. Id prefixes make the three namespaces disjoint, so checking
        # questions up front cannot shadow an answer or comment.
        cur = self._execute("SELECT data FROM acq.questions WHERE id = %s", (content_id,))
        row = cur.fetchone()
        if row is not None:
            return self._review_question(Question.model_validate_json(row[0]), new_status)

        for table, cls in (("answers", Answer), ("comments", Comment)):
            cur = self._execute(f"SELECT data, status FROM acq.{table} WHERE id = %s", (content_id,))
            row = cur.fetchone()
            if row is None:
                continue
            if row[1] == new_status:
                return False
            updated = cls.model_validate_json(row[0]).model_copy(update={"status": new_status})
            self._execute(
                f"UPDATE acq.{table} SET data = %s, status = %s WHERE id = %s",
                (updated.model_dump_json(), new_status, content_id),
            )
            self._conn.commit()
            return True
        return None

    def _review_question(self, q: Question, new_status: str) -> bool:
        """Apply one approve/reject verdict to a question and its answers.

        A new question is reviewed as a single card together with the answers
        filed under it, so approving promotes every answer still pending in the
        same transaction.

        Rejection deliberately leaves those answers pending. A rejected
        question is invisible, and pending_queue refuses to surface answers
        whose parent question is not live, so its pending answers are already
        unreachable. Leaving them pending is what makes the reject reversible:
        a later approve promotes them normally. Cascading the rejection onto
        the answer rows would make approve and reject asymmetric and
        unrecoverable.
        """
        if new_status == "approved":
            # 'resolved' is a live status too, so an approve there is a no-op
            # rather than a demotion back to 'open'.
            if q.status in ("open", "resolved"):
                return False
            cur = self._execute(
                "SELECT id, data FROM acq.answers WHERE question_id = %s AND status = 'pending'",
                (q.id,),
            )
            for answer_id, data_json in cur.fetchall():
                promoted = Answer.model_validate_json(data_json).model_copy(update={"status": "approved"})
                self._execute(
                    "UPDATE acq.answers SET data = %s, status = 'approved' WHERE id = %s",
                    (promoted.model_dump_json(), answer_id),
                )
            # Commits the answer promotions above along with the question row.
            self._write_question_status(q, "open")
            return True

        if q.status == "deleted":
            return False
        self._write_question_status(q, "deleted")
        return True

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def pending_queue(self) -> dict[str, list[Any]]:
        """Content awaiting a human verdict, oldest first within each kind.

        Answers and comments are filtered on parent liveness. An answer under a
        pending or rejected question is not a review card of its own: the
        question is judged as one unit together with its answers. Without that
        filter, rejecting a question would strand its answers in the queue as
        orphan cards with no context to judge them by.
        """
        cur = self._execute("SELECT data FROM acq.questions WHERE status = 'pending' ORDER BY created_at ASC")
        question_rows = cur.fetchall()
        cur = self._execute(
            "SELECT a.data FROM acq.answers a JOIN acq.questions q ON q.id = a.question_id"
            " WHERE a.status = 'pending' AND q.status IN ('open', 'resolved')"
            " ORDER BY a.created_at ASC"
        )
        answer_rows = cur.fetchall()
        cur = self._execute(
            "SELECT c.data FROM acq.comments c WHERE c.status = 'pending' AND ("
            "  (c.parent_type = 'question' AND EXISTS ("
            "     SELECT 1 FROM acq.questions q WHERE q.id = c.parent_id AND q.status IN ('open', 'resolved')))"
            "  OR (c.parent_type = 'answer' AND EXISTS ("
            "     SELECT 1 FROM acq.answers a JOIN acq.questions q ON q.id = a.question_id"
            "     WHERE a.id = c.parent_id AND a.status = 'approved' AND q.status IN ('open', 'resolved')))"
            ") ORDER BY c.created_at ASC"
        )
        comment_rows = cur.fetchall()
        return {
            "questions": [Question.model_validate_json(r[0]) for r in question_rows],
            "answers": [Answer.model_validate_json(r[0]) for r in answer_rows],
            "comments": [Comment.model_validate_json(r[0]) for r in comment_rows],
        }

    def get_question_thread(
        self, question_id: str, include_pending: bool = False, include_deleted: bool = False
    ) -> dict[str, Any] | None:
        """Assemble a question with its ranked answers and their comments.

        *include_pending* adds answers still awaiting review, and is also what
        lets a question that is itself still awaiting review be read at all —
        only the review queue and the curation UI pass it. *include_deleted*
        additionally returns soft-deleted questions along with rejected answers
        and comments; only the human curation UI passes it, so agent-facing
        reads never see deleted content.
        """
        q = self.get_question(question_id)
        if q is None or (q.status == "deleted" and not include_deleted):
            return None
        if q.status == "pending" and not include_pending:
            return None

        answer_statuses = ["approved"]
        if include_pending:
            answer_statuses.append("pending")
        if include_deleted:
            answer_statuses.append("rejected")
        # Pending comments belong to the review queue rather than the thread,
        # so only soft-deleted ones join, letting the UI offer a restore.
        comment_statuses = ["approved", "rejected"] if include_deleted else ["approved"]

        cur = self._execute(
            "SELECT data FROM acq.answers WHERE question_id = %s AND status = ANY(%s)",
            (question_id, answer_statuses),
        )
        all_answers = [Answer.model_validate_json(r[0]) for r in cur.fetchall()]
        # Only approved answers are ranked against each other; pending and
        # rejected ones trail behind so ranking stays a statement about the
        # answers a reader is meant to weigh.
        ranked = rank_answers([a for a in all_answers if a.status == "approved"], q.pinned_answer_id)
        ranked += [a for a in all_answers if a.status == "pending"]
        ranked += [a for a in all_answers if a.status == "rejected"]

        cur = self._execute(
            "SELECT data FROM acq.comments WHERE parent_id = %s AND parent_type = 'question' AND status = ANY(%s)",
            (question_id, comment_statuses),
        )
        q_comments = [Comment.model_validate_json(r[0]) for r in cur.fetchall()]

        answer_threads = []
        for answer in ranked:
            cur = self._execute(
                "SELECT data FROM acq.comments WHERE parent_id = %s AND parent_type = 'answer' AND status = ANY(%s)",
                (answer.id, comment_statuses),
            )
            a_comments = [Comment.model_validate_json(r[0]) for r in cur.fetchall()]
            answer_threads.append({"answer": answer, "comments": a_comments})

        tag_names = self._get_question_tag_names(question_id)

        return {
            "question": q,
            "tags": [{"name": n} for n in sorted(tag_names)],
            "comments": q_comments,
            "answers": answer_threads,
        }

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        language: str | None = None,
        framework: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Tsvector + tag Jaccard search returning ranked question threads."""
        query_tags = set(tags or [])

        words = query.strip().split()
        if not words:
            return []
        tsquery_str = " | ".join(w.replace("-", " & ") if "-" in w else w for w in words if w)

        try:
            # Search questions
            cur = self._execute(
                """
                SELECT id, ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM acq.questions
                WHERE search_vector @@ to_tsquery('english', %s)
                """,
                (tsquery_str, tsquery_str),
            )
            q_rows = cur.fetchall()

            # Search answers
            cur = self._execute(
                """
                SELECT question_id, ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM acq.answers
                WHERE search_vector @@ to_tsquery('english', %s)
                  -- Exclude soft-deleted answers only. Whether a pending
                  -- answer should steer search predates soft-delete.
                  AND status <> 'rejected'
                """,
                (tsquery_str, tsquery_str),
            )
            a_rows = cur.fetchall()
        except Exception:
            self._conn.rollback()
            return []

        # Collect best rank per question and track match sources.
        best_rank_per_question: dict[str, float] = {}
        matched_sources: dict[str, set[str]] = {}
        for qid, rank in q_rows:
            matched_sources.setdefault(qid, set()).add("question")
            current = best_rank_per_question.get(qid)
            if current is None or rank > current:
                best_rank_per_question[qid] = rank
        for qid, rank in a_rows:
            matched_sources.setdefault(qid, set()).add("answer")
            current = best_rank_per_question.get(qid)
            if current is None or rank > current:
                best_rank_per_question[qid] = rank

        if not best_rank_per_question:
            return []

        raw_ranks = list(best_rank_per_question.values())
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)

        scored: list[tuple[float, str, list[str]]] = []
        for question_id, raw_rank in best_rank_per_question.items():
            q = self.get_question(question_id)
            # A question that is soft-deleted or still awaiting review is not
            # part of the readable corpus, so it is dropped even when its
            # tsvector still matches.
            if q is None or q.status in ("deleted", "pending"):
                continue

            normalized_rank = _normalized_rank(raw_rank, min_rank, max_rank)

            q_tags = self._get_question_tag_names(question_id)
            if query_tags or q_tags:
                intersection = len(query_tags & q_tags)
                union = len(query_tags | q_tags)
                jaccard = intersection / union if union > 0 else 0.0
            else:
                jaccard = 0.0

            language_match = language is not None and (
                q.context_language is not None and q.context_language.lower() == language.lower()
            )
            framework_match = framework is not None and (
                q.context_framework is not None and q.context_framework.lower() == framework.lower()
            )

            text_rel = text_relevance_score(
                fts_rank=normalized_rank,
                tag_jaccard=jaccard,
                language_match=language_match,
                framework_match=framework_match,
            )

            cur = self._execute(
                "SELECT data FROM acq.answers WHERE question_id = %s AND status = 'approved'",
                (question_id,),
            )
            answer_rows = cur.fetchall()
            answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
            ranked_answers = rank_answers(answers, q.pinned_answer_id)
            best_answer = ranked_answers[0] if ranked_answers else None

            final_score = search_score(
                text_relevance=text_rel,
                question=q,
                best_answer=best_answer,
            )

            matched_on: list[str] = list(matched_sources.get(question_id, set()))
            if jaccard > 0:
                matched_on.append("tags")

            scored.append((final_score, question_id, matched_on))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        results = []
        for score, question_id, matched_on in scored:
            thread = self.get_question_thread(question_id)
            if thread is None:
                continue
            thread["answers"] = thread["answers"][:3]
            thread["_score"] = round(score, 3)
            thread["_matched_on"] = matched_on
            results.append(thread)

        return results

    def find_similar_questions(self, title: str, tag_names: list[str]) -> list[dict[str, Any]]:
        """Find questions that look like duplicates of *title*, best 3 first.

        The tsvector query only narrows the candidate set; the decision uses
        the absolute ``duplicate_similarity`` measure so a lone weak text
        match cannot register as a duplicate.
        """
        query_tags = set(tag_names)

        words = title.strip().split()
        if not words:
            return []
        tsquery_str = " | ".join(w.replace("-", " & ") if "-" in w else w for w in words if w)

        try:
            cur = self._execute(
                """
                SELECT id
                FROM acq.questions
                WHERE search_vector @@ to_tsquery('english', %s)
                ORDER BY ts_rank(search_vector, to_tsquery('english', %s)) DESC
                LIMIT %s
                """,
                (tsquery_str, tsquery_str, _CANDIDATE_LIMIT),
            )
            fts_rows = cur.fetchall()
        except Exception:
            self._conn.rollback()
            return []

        scored = []
        for (question_id,) in fts_rows:
            q = self.get_question(question_id)
            # Questions still awaiting review stay eligible as duplicates on
            # purpose. They are invisible to search, so hiding them here too
            # would let agents refile the same question over and over while
            # the first one waits in the queue.
            if q is None or q.status == "deleted":
                continue

            similarity = duplicate_similarity(
                query_title=title,
                candidate_title=q.title,
                query_tags=query_tags,
                candidate_tags=self._get_question_tag_names(question_id),
            )
            if similarity >= DUPLICATE_THRESHOLD:
                scored.append((similarity, q))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"question": q, "similarity": score} for score, q in scored[:3]]

    def _get_question_tag_names(self, question_id: str) -> set[str]:
        cur = self._execute(
            "SELECT t.name FROM acq.tags t JOIN acq.question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = %s",
            (question_id,),
        )
        rows = cur.fetchall()
        return {r[0] for r in rows}

    def _refresh_question_tsvector(self, question_id: str) -> None:
        """Rebuild the tsvector for a single question with current tag names."""
        q = self.get_question(question_id)
        if q is None:
            return
        tag_text = " ".join(sorted(self._get_question_tag_names(question_id)))
        self._execute(
            "UPDATE acq.questions SET search_vector ="
            " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
            (q.title, q.body, tag_text, question_id),
        )

    def get_status(self) -> dict[str, Any]:
        # A question still awaiting review is not part of the corpus yet, so
        # the headline counts treat it like a deleted one and it is reported
        # separately as pending_questions instead.
        total_questions = self._execute(
            "SELECT COUNT(*) FROM acq.questions WHERE status NOT IN ('deleted', 'pending')"
        ).fetchone()[0]
        total_answers = self._execute("SELECT COUNT(*) FROM acq.answers WHERE status = 'approved'").fetchone()[0]
        total_tags = self._execute("SELECT COUNT(*) FROM acq.tags").fetchone()[0]
        total_votes = self._execute("SELECT COUNT(*) FROM acq.votes").fetchone()[0]
        unanswered = self._execute(
            "SELECT COUNT(DISTINCT q.id) FROM acq.questions q LEFT JOIN acq.answers a ON a.question_id = q.id AND a.status = 'approved' WHERE a.id IS NULL AND q.status NOT IN ('deleted', 'pending')"
        ).fetchone()[0]
        pending_questions = self._execute("SELECT COUNT(*) FROM acq.questions WHERE status = 'pending'").fetchone()[0]
        pending_answers = self._execute("SELECT COUNT(*) FROM acq.answers WHERE status = 'pending'").fetchone()[0]
        pending_comments = self._execute("SELECT COUNT(*) FROM acq.comments WHERE status = 'pending'").fetchone()[0]
        return {
            "total_questions": total_questions,
            "total_answers": total_answers,
            "total_tags": total_tags,
            "total_votes": total_votes,
            "unanswered": unanswered,
            "pending_questions": pending_questions,
            "pending": pending_answers + pending_comments,
        }

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_since(self, since: str | None = None) -> dict:
        if since:
            questions = self._execute(
                "SELECT data FROM acq.questions WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            answers = self._execute(
                "SELECT data FROM acq.answers WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            votes = self._execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM acq.votes WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            comments = self._execute(
                "SELECT data FROM acq.comments WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            questions = self._execute("SELECT data FROM acq.questions ORDER BY created_at").fetchall()
            answers = self._execute("SELECT data FROM acq.answers ORDER BY created_at").fetchall()
            votes = self._execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM acq.votes ORDER BY created_at"
            ).fetchall()
            comments = self._execute("SELECT data FROM acq.comments ORDER BY created_at").fetchall()

        tags = self._execute("SELECT id, name, description, usage_count FROM acq.tags ORDER BY name").fetchall()
        question_tags = self._execute("SELECT question_id, tag_id FROM acq.question_tags").fetchall()

        return {
            "questions": [json.loads(r[0]) for r in questions],
            "answers": [json.loads(r[0]) for r in answers],
            "tags": [{"id": r[0], "name": r[1], "description": r[2], "usage_count": r[3]} for r in tags],
            "question_tags": [{"question_id": r[0], "tag_id": r[1]} for r in question_tags],
            "votes": [
                {
                    "id": r[0],
                    "target_id": r[1],
                    "target_type": r[2],
                    "voter_id": r[3],
                    "voter_type": r[4],
                    "value": r[5],
                    "created_at": str(r[6]),
                }
                for r in votes
            ],
            "comments": [json.loads(r[0]) for r in comments],
        }

    def bulk_upsert(self, data: dict) -> int:
        count = 0

        # Build tag-name lookup so we can include tags in tsvectors.
        tag_names_by_id = {t["id"]: t["name"] for t in data.get("tags", [])}
        q_tag_map: dict[str, list[str]] = {}
        for qt in data.get("question_tags", []):
            name = tag_names_by_id.get(qt["tag_id"], "")
            if name:
                q_tag_map.setdefault(qt["question_id"], []).append(name)

        for q_data in data.get("questions", []):
            q = Question.model_validate(q_data)
            self._execute(
                """
                INSERT INTO acq.questions (id, data, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at
                """,
                (
                    q.id,
                    q.model_dump_json(),
                    q.status,
                    q.created_at.isoformat(),
                    q.updated_at.isoformat(),
                ),
            )
            tag_text = " ".join(q_tag_map.get(q.id, []))
            self._execute(
                "UPDATE acq.questions SET search_vector ="
                " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
                (q.title, q.body, tag_text, q.id),
            )
            count += 1

        for a_data in data.get("answers", []):
            a = Answer.model_validate(a_data)
            self._execute(
                """
                INSERT INTO acq.answers (id, question_id, data, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET question_id = EXCLUDED.question_id, data = EXCLUDED.data,
                    status = EXCLUDED.status, created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at
                """,
                (
                    a.id,
                    a.question_id,
                    a.model_dump_json(),
                    a.status,
                    a.created_at.isoformat(),
                    a.updated_at.isoformat(),
                ),
            )
            self._execute(
                "UPDATE acq.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
                (a.body, a.id),
            )
            count += 1

        for t_data in data.get("tags", []):
            self._execute(
                """
                INSERT INTO acq.tags (id, name, description, usage_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                    usage_count = EXCLUDED.usage_count
                """,
                (t_data["id"], t_data["name"], t_data.get("description"), t_data.get("usage_count", 0)),
            )
            count += 1

        for qt_data in data.get("question_tags", []):
            self._execute(
                "INSERT INTO acq.question_tags (question_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (qt_data["question_id"], qt_data["tag_id"]),
            )

        for v_data in data.get("votes", []):
            self._execute(
                """
                INSERT INTO acq.votes (id, target_id, target_type, voter_id, voter_type, value, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    v_data["id"],
                    v_data["target_id"],
                    v_data["target_type"],
                    v_data["voter_id"],
                    v_data["voter_type"],
                    v_data["value"],
                    v_data["created_at"],
                ),
            )
            count += 1

        for c_data in data.get("comments", []):
            c = Comment.model_validate(c_data)
            self._execute(
                """
                INSERT INTO acq.comments (id, parent_id, parent_type, data, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET parent_id = EXCLUDED.parent_id, parent_type = EXCLUDED.parent_type,
                    data = EXCLUDED.data, status = EXCLUDED.status, created_at = EXCLUDED.created_at
                """,
                (
                    c.id,
                    c.parent_id,
                    c.parent_type,
                    c.model_dump_json(),
                    c.status,
                    c.created_at.isoformat(),
                ),
            )
            count += 1

        self._conn.commit()
        return count

    def close(self) -> None:
        self._conn.close()


def _row_to_edit_history(row: tuple) -> EditHistory:
    return EditHistory(
        id=row[0],
        target_id=row[1],
        target_type=row[2],
        previous_body=row[3],
        new_body=row[4],
        edited_by=row[5],
        edited_by_type=row[6],
        edited_at=datetime.fromisoformat(str(row[7])),
    )
