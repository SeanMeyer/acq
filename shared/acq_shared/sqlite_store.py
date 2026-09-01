"""SqliteStore — shared SQLite-backed Store implementation.

Satisfies the Store protocol defined in acq_shared.store. Uses FTS5 for
full-text search, WAL mode for concurrency, and stores model data as
JSON blobs alongside indexed columns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from acq_shared.models import Answer, Comment, EditHistory, Question, Tag, Vote
from acq_shared.scoring import (
    DUPLICATE_THRESHOLD,
    duplicate_similarity,
    rank_answers,
    search_score,
    text_relevance_score,
)
from acq_shared.sqlite_schema import create_tables


def _fts_or_query(text: str) -> str:
    """Build an FTS5 MATCH expression that ORs the words of *text*.

    FTS5 treats space-separated bare terms as an implicit AND, so passing a
    multi-word title straight through demands that *every* word appear in the
    row. Candidate retrieval wants the opposite: any overlapping word makes a
    row worth scoring, and the caller ranks what comes back. Postgres builds
    its tsquery with ``|`` for the same reason, so ORing here is also what
    keeps the two backends returning the same candidates.

    Each term is double-quoted so punctuation cannot be parsed as FTS5
    operator syntax, with embedded double quotes doubled to escape them.
    Returns "" when *text* has no usable words; callers must treat that as
    "no candidates" rather than passing it to MATCH.
    """
    words = [w.replace('"', '""') for w in text.split() if w.strip()]
    return " OR ".join(f'"{w}"' for w in words)


# Upper bound on rows pulled from FTS before absolute scoring. ORing the terms
# of a title means one common word can match a large slice of a mature corpus,
# and each candidate then costs two further queries to hydrate. Only the best
# three survive, so taking the most text-relevant candidates and stopping is
# enough, and it keeps the cost independent of corpus size.
_CANDIDATE_LIMIT = 50


class SqliteStore:
    """SQLite-backed store implementing the Store protocol.

    Constructor takes an existing sqlite3.Connection so callers control
    lifecycle. Calls create_tables() to ensure schema exists.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        create_tables(conn)
        self._ensure_users_table()

    def _ensure_users_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, username: str, password_hash: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, now),
        )
        self._conn.commit()

    def get_user(self, username: str) -> dict[str, str] | None:
        row = self._conn.execute(
            "SELECT username, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {"username": row[0], "password_hash": row[1], "created_at": row[2]}

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
        tag = Tag(name=name)  # normalize via field_validator
        row = self._conn.execute(
            "SELECT id, name, description, usage_count FROM tags WHERE name = ?",
            (tag.name,),
        ).fetchone()
        if row is not None:
            return Tag(id=row[0], name=row[1], description=row[2], usage_count=row[3])
        self._conn.execute(
            "INSERT INTO tags (id, name, description, usage_count) VALUES (?, ?, ?, ?)",
            (tag.id, tag.name, tag.description, tag.usage_count),
        )
        return tag

    def merge_tags(self, source_id: str, target_id: str) -> None:
        """Repoint all question_tags rows from source to target, delete source."""
        # Collect affected questions before the merge so we can refresh their FTS entries.
        affected_rows = self._conn.execute(
            "SELECT question_id FROM question_tags WHERE tag_id = ? OR tag_id = ?",
            (source_id, target_id),
        ).fetchall()
        affected_qids = {r[0] for r in affected_rows}

        self._conn.execute(
            """
            UPDATE question_tags SET tag_id = ?
            WHERE tag_id = ?
              AND question_id NOT IN (
                  SELECT question_id FROM question_tags WHERE tag_id = ?
              )
            """,
            (target_id, source_id, target_id),
        )
        self._conn.execute("DELETE FROM question_tags WHERE tag_id = ?", (source_id,))
        self._conn.execute("DELETE FROM tags WHERE id = ?", (source_id,))
        row = self._conn.execute("SELECT COUNT(*) FROM question_tags WHERE tag_id = ?", (target_id,)).fetchone()
        self._conn.execute("UPDATE tags SET usage_count = ? WHERE id = ?", (row[0], target_id))

        # Refresh FTS entries for affected questions so the tags column stays current.
        for qid in affected_qids:
            self._refresh_question_fts(qid)

        self._conn.commit()

    def list_tags(self, q: str | None = None) -> list[Tag]:
        if q:
            rows = self._conn.execute(
                "SELECT id, name, description, usage_count FROM tags WHERE name LIKE ?",
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, name, description, usage_count FROM tags ORDER BY usage_count DESC"
            ).fetchall()
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
        self._conn.execute(
            "INSERT INTO questions (id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
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
            self._conn.execute(
                "INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)",
                (question.id, tag.id),
            )
            self._conn.execute("UPDATE tags SET usage_count = usage_count + 1 WHERE id = ?", (tag.id,))
        tag_text = " ".join(t.name for t in tags)
        self._conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (question.id, "question", question.id, question.title, question.body, tag_text),
        )
        self._conn.commit()
        return question

    def get_question(self, question_id: str) -> Question | None:
        row = self._conn.execute("SELECT data FROM questions WHERE id = ?", (question_id,)).fetchone()
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
        self._conn.execute(
            "INSERT INTO edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        current = {
            r[0]
            for r in self._conn.execute(
                "SELECT tag_id FROM question_tags WHERE question_id = ?", (question_id,)
            ).fetchall()
        }
        for tag_id in current - desired:
            self._conn.execute(
                "DELETE FROM question_tags WHERE question_id = ? AND tag_id = ?",
                (question_id, tag_id),
            )
        for tag_id in desired - current:
            self._conn.execute(
                "INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)",
                (question_id, tag_id),
            )
        for tag_id in current | desired:
            count = self._conn.execute("SELECT COUNT(*) FROM question_tags WHERE tag_id = ?", (tag_id,)).fetchone()[0]
            self._conn.execute("UPDATE tags SET usage_count = ? WHERE id = ?", (count, tag_id))

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
        self._conn.execute(
            "UPDATE questions SET data = ?, updated_at = ? WHERE id = ?",
            (updated.model_dump_json(), now.isoformat(), question_id),
        )
        # Reads the row written just above, so it must follow the UPDATE.
        self._refresh_question_fts(question_id)
        self._conn.commit()
        return updated

    def pin_answer(self, question_id: str, answer_id: str) -> Question | None:
        q = self.get_question(question_id)
        if q is None:
            return None
        updated = q.model_copy(update={"pinned_answer_id": answer_id})
        self._conn.execute(
            "UPDATE questions SET data = ? WHERE id = ?",
            (updated.model_dump_json(), question_id),
        )
        self._conn.commit()
        return updated

    def unpin_answer(self, question_id: str) -> Question | None:
        q = self.get_question(question_id)
        if q is None:
            return None
        updated = q.model_copy(update={"pinned_answer_id": None})
        self._conn.execute(
            "UPDATE questions SET data = ? WHERE id = ?",
            (updated.model_dump_json(), question_id),
        )
        self._conn.commit()
        return updated

    def get_question_history(self, question_id: str) -> list[EditHistory]:
        rows = self._conn.execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM edit_history WHERE target_id = ? AND target_type IN ('question', 'question_title') ORDER BY edited_at ASC",
            (question_id,),
        ).fetchall()
        return [_row_to_edit_history(r) for r in rows]

    def _write_question_status(self, q: Question, status: str) -> None:
        now = datetime.now(UTC)
        updated = q.model_copy(update={"status": status, "updated_at": now})
        self._conn.execute(
            "UPDATE questions SET data = ?, status = ?, updated_at = ? WHERE id = ?",
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
            where_clauses.append("q.status = ?")
            params.append(status)
        else:
            # Questions awaiting review and soft-deleted ones are both hidden
            # unless asked for by name; status='pending' is how the curation
            # UI lists the review queue.
            where_clauses.append("q.status NOT IN ('deleted', 'pending')")
        if tag is not None:
            join = " JOIN question_tags qt ON q.id = qt.question_id JOIN tags t ON qt.tag_id = t.id"
            where_clauses.append("t.name = ?")
            params.append(tag)

        where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total = self._conn.execute(f"SELECT COUNT(DISTINCT q.id) FROM questions q{join}{where}", params).fetchone()[0]

        rows = self._conn.execute(
            f"SELECT DISTINCT q.data FROM questions q{join}{where} ORDER BY q.created_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        results: list[dict] = []
        for (data_json,) in rows:
            q = Question.model_validate_json(data_json)
            tag_names = self._get_question_tag_names(q.id)
            tags = [{"name": n} for n in sorted(tag_names)]
            answer_count = self._conn.execute(
                "SELECT COUNT(*) FROM answers WHERE question_id = ? AND status IN ('approved', 'pending')",
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
        self._conn.execute(
            "INSERT INTO answers (id, question_id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                answer.id,
                answer.question_id,
                answer.model_dump_json(),
                answer.status,
                answer.created_at.isoformat(),
                answer.updated_at.isoformat(),
            ),
        )
        self._conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (answer.id, "answer", answer.question_id, "", answer.body, ""),
        )
        self._conn.commit()
        return answer

    def get_answer(self, answer_id: str) -> Answer | None:
        row = self._conn.execute("SELECT data FROM answers WHERE id = ?", (answer_id,)).fetchone()
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
        self._conn.execute(
            "INSERT INTO edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        self._conn.execute(
            "UPDATE answers SET data = ?, updated_at = ? WHERE id = ?",
            (updated.model_dump_json(), now.isoformat(), answer_id),
        )
        self._conn.execute(
            "DELETE FROM search_index WHERE entity_id = ? AND entity_type = 'answer'",
            (answer_id,),
        )
        self._conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (answer_id, "answer", updated.question_id, "", updated.body, ""),
        )
        self._conn.commit()
        return updated

    def get_answer_history(self, answer_id: str) -> list[EditHistory]:
        rows = self._conn.execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM edit_history WHERE target_id = ? AND target_type = 'answer' ORDER BY edited_at ASC",
            (answer_id,),
        ).fetchall()
        return [_row_to_edit_history(r) for r in rows]

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def create_comment(self, comment: Comment) -> Comment:
        self._conn.execute(
            "INSERT INTO comments (id, parent_id, parent_type, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                comment.id,
                comment.parent_id,
                comment.parent_type,
                comment.model_dump_json(),
                comment.status,
                comment.created_at.isoformat(),
                comment.updated_at.isoformat(),
            ),
        )
        self._conn.commit()
        return comment

    def get_comment(self, comment_id: str) -> Comment | None:
        row = self._conn.execute("SELECT data FROM comments WHERE id = ?", (comment_id,)).fetchone()
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
        now = datetime.now(UTC)
        updated = c.model_copy(update={"body": new_body, "updated_at": now})
        self._conn.execute(
            "UPDATE comments SET data = ?, updated_at = ? WHERE id = ?",
            (updated.model_dump_json(), now.isoformat(), comment_id),
        )
        self._conn.commit()
        return updated

    def get_comment_history(self, comment_id: str) -> list[EditHistory]:
        rows = self._conn.execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM edit_history WHERE target_id = ? AND target_type = 'comment' ORDER BY edited_at ASC",
            (comment_id,),
        ).fetchall()
        return [_row_to_edit_history(r) for r in rows]

    # ------------------------------------------------------------------
    # Votes
    # ------------------------------------------------------------------

    def cast_vote(self, vote: Vote) -> dict[str, Any]:
        """Cast a vote; returns updated counts dict or error dict."""
        existing = self._conn.execute(
            "SELECT created_at FROM votes WHERE target_id = ? AND voter_id = ? AND voter_type = ?",
            (vote.target_id, vote.voter_id, vote.voter_type),
        ).fetchone()
        if existing is not None:
            return {"error": "duplicate_vote"}

        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        recent = self._conn.execute(
            "SELECT created_at FROM votes WHERE target_id = ? AND voter_id = ? AND voter_type = ? AND created_at >= ?",
            (vote.target_id, vote.voter_id, vote.voter_type, cutoff),
        ).fetchone()
        if recent is not None:
            return {"error": "rate_limited"}

        try:
            self._conn.execute(
                "INSERT INTO votes (id, target_id, target_type, voter_id, voter_type, value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        except sqlite3.IntegrityError:
            return {"error": "duplicate_vote"}

        counts = self._recalculate_vote_counts(vote.target_id, vote.target_type)
        self._conn.commit()
        return counts

    def _recalculate_vote_counts(self, target_id: str, target_type: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT voter_type, value, COUNT(*) FROM votes WHERE target_id = ? GROUP BY voter_type, value",
            (target_id,),
        ).fetchall()
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
            data_row = self._conn.execute("SELECT data FROM questions WHERE id = ?", (target_id,)).fetchone()
            if data_row:
                q = Question.model_validate_json(data_row[0])
                updated = q.model_copy(update=counts)
                self._conn.execute(
                    "UPDATE questions SET data = ? WHERE id = ?",
                    (updated.model_dump_json(), target_id),
                )
        elif target_type == "answer":
            data_row = self._conn.execute("SELECT data FROM answers WHERE id = ?", (target_id,)).fetchone()
            if data_row:
                a = Answer.model_validate_json(data_row[0])
                updated = a.model_copy(update=counts)
                self._conn.execute(
                    "UPDATE answers SET data = ? WHERE id = ?",
                    (updated.model_dump_json(), target_id),
                )
        return counts

    def delete_vote(self, target_id: str, voter_id: str, voter_type: str) -> bool:
        row = self._conn.execute(
            "SELECT target_type FROM votes WHERE target_id = ? AND voter_id = ? AND voter_type = ?",
            (target_id, voter_id, voter_type),
        ).fetchone()
        if row is None:
            return False
        target_type = row[0]
        self._conn.execute(
            "DELETE FROM votes WHERE target_id = ? AND voter_id = ? AND voter_type = ?",
            (target_id, voter_id, voter_type),
        )
        self._recalculate_vote_counts(target_id, target_type)
        self._conn.commit()
        return True

    def get_user_votes(self, voter_id: str, voter_type: str, target_ids: list[str]) -> dict[str, int]:
        if not target_ids:
            return {}
        placeholders = ",".join("?" for _ in target_ids)
        rows = self._conn.execute(
            f"SELECT target_id, value FROM votes WHERE voter_id = ? AND voter_type = ? AND target_id IN ({placeholders})",
            [voter_id, voter_type, *target_ids],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

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
        row = self._conn.execute("SELECT data FROM questions WHERE id = ?", (content_id,)).fetchone()
        if row is not None:
            return self._review_question(Question.model_validate_json(row[0]), new_status)

        model = {"answers": Answer, "comments": Comment}
        for table, cls in model.items():
            row = self._conn.execute(f"SELECT data, status FROM {table} WHERE id = ?", (content_id,)).fetchone()
            if row is None:
                continue
            if row[1] == new_status:
                return False
            now = datetime.now(UTC)
            updated = cls.model_validate_json(row[0]).model_copy(update={"status": new_status, "updated_at": now})
            self._conn.execute(
                f"UPDATE {table} SET data = ?, status = ?, updated_at = ? WHERE id = ?",
                (updated.model_dump_json(), new_status, now.isoformat(), content_id),
            )
            self._conn.commit()
            return True
        return None

    def _review_question(self, q: Question, new_status: str) -> bool:
        """Apply one approve/reject verdict to a question and its answers.

        A new pending question is reviewed as a single card together with the
        answers filed under it, so approving that card promotes every pending
        answer in the same transaction. Restoring a previously deleted question
        only restores the question; otherwise an unrelated answer submitted
        while it was deleted could be published without review.

        Rejection leaves bundled answers pending and unreachable while their
        parent is deleted. If the question is restored, those answers enter the
        ordinary answer queue instead of being silently approved.
        """
        if new_status == "approved":
            # 'resolved' is a live status too, so an approve there is a no-op
            # rather than a demotion back to 'open'.
            if q.status in ("open", "resolved"):
                return False
            if q.status == "pending":
                now = datetime.now(UTC)
                rows = self._conn.execute(
                    "SELECT id, data FROM answers WHERE question_id = ? AND status = 'pending'",
                    (q.id,),
                ).fetchall()
                for answer_id, data_json in rows:
                    promoted = Answer.model_validate_json(data_json).model_copy(
                        update={"status": "approved", "updated_at": now}
                    )
                    self._conn.execute(
                        "UPDATE answers SET data = ?, status = 'approved', updated_at = ? WHERE id = ?",
                        (promoted.model_dump_json(), now.isoformat(), answer_id),
                    )
            # Commits any answer promotions above along with the question row.
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
        question_rows = self._conn.execute(
            "SELECT data FROM questions WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        answer_rows = self._conn.execute(
            "SELECT a.data FROM answers a JOIN questions q ON q.id = a.question_id"
            " WHERE a.status = 'pending' AND q.status IN ('open', 'resolved')"
            " ORDER BY a.created_at ASC"
        ).fetchall()
        comment_rows = self._conn.execute(
            "SELECT c.data FROM comments c WHERE c.status = 'pending' AND ("
            "  (c.parent_type = 'question' AND EXISTS ("
            "     SELECT 1 FROM questions q WHERE q.id = c.parent_id AND q.status IN ('open', 'resolved')))"
            "  OR (c.parent_type = 'answer' AND EXISTS ("
            "     SELECT 1 FROM answers a JOIN questions q ON q.id = a.question_id"
            "     WHERE a.id = c.parent_id AND a.status = 'approved' AND q.status IN ('open', 'resolved')))"
            ") ORDER BY c.created_at ASC"
        ).fetchall()
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
        a_placeholders = ",".join("?" for _ in answer_statuses)
        c_placeholders = ",".join("?" for _ in comment_statuses)

        answer_rows = self._conn.execute(
            f"SELECT data FROM answers WHERE question_id = ? AND status IN ({a_placeholders})",
            (question_id, *answer_statuses),
        ).fetchall()
        all_answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
        # Only approved answers are ranked against each other; pending and
        # rejected ones trail behind so ranking stays a statement about the
        # answers a reader is meant to weigh.
        ranked = rank_answers([a for a in all_answers if a.status == "approved"], q.pinned_answer_id)
        ranked += [a for a in all_answers if a.status == "pending"]
        ranked += [a for a in all_answers if a.status == "rejected"]

        comment_rows = self._conn.execute(
            "SELECT data FROM comments WHERE parent_id = ? AND parent_type = 'question'"
            f" AND status IN ({c_placeholders})",
            (question_id, *comment_statuses),
        ).fetchall()
        q_comments = [Comment.model_validate_json(r[0]) for r in comment_rows]

        answer_threads = []
        for answer in ranked:
            a_comment_rows = self._conn.execute(
                "SELECT data FROM comments WHERE parent_id = ? AND parent_type = 'answer'"
                f" AND status IN ({c_placeholders})",
                (answer.id, *comment_statuses),
            ).fetchall()
            a_comments = [Comment.model_validate_json(r[0]) for r in a_comment_rows]
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
        """FTS5 + tag Jaccard search returning ranked question threads."""
        query_tags = set(tags or [])

        fts_query = _fts_or_query(query)
        if not fts_query:
            return []
        try:
            fts_rows = self._conn.execute(
                "SELECT entity_id, entity_type, question_id, rank FROM search_index WHERE search_index MATCH ? ORDER BY rank",
                (fts_query,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        # Drop matches on answers that are no longer visible. The FTS index is
        # written at creation and never pruned, so a rejected (soft-deleted)
        # answer keeps matching and would otherwise resurface its question.
        fts_rows = self._filter_visible_matches(fts_rows)
        if not fts_rows:
            return []

        raw_ranks = [r[3] for r in fts_rows]
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        best_rank_per_question: dict[str, float] = {}
        matched_entity_types: dict[str, set[str]] = {}
        for entity_id, entity_type, question_id, rank in fts_rows:
            matched_entity_types.setdefault(question_id, set()).add(entity_type)
            current = best_rank_per_question.get(question_id)
            if current is None or rank < current:
                best_rank_per_question[question_id] = rank

        scored: list[tuple[float, str, list[str]]] = []
        for question_id, raw_rank in best_rank_per_question.items():
            q = self.get_question(question_id)
            # The FTS index is written at creation and never pruned, so a
            # question that is soft-deleted or still awaiting review keeps
            # matching and has to be dropped here.
            if q is None or q.status in ("deleted", "pending"):
                continue

            normalized_rank = 1.0 - (raw_rank - min_rank) / rank_range

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

            answer_rows = self._conn.execute(
                "SELECT data FROM answers WHERE question_id = ? AND status = 'approved'",
                (question_id,),
            ).fetchall()
            answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
            ranked_answers = rank_answers(answers, q.pinned_answer_id)
            best_answer = ranked_answers[0] if ranked_answers else None

            final_score = search_score(
                text_relevance=text_rel,
                question=q,
                best_answer=best_answer,
            )

            matched_on: list[str] = []
            etypes = matched_entity_types.get(question_id, set())
            if "question" in etypes:
                matched_on.append("question")
            if "answer" in etypes:
                matched_on.append("answer")
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
        """Find questions that may be duplicates of *title*, best 3 first.

        FTS5 only narrows the candidate set; ranking and admission use the
        absolute ``duplicate_similarity`` measure, so a lone weak text match
        cannot register as a duplicate on text alone.
        """
        query_tags = set(tag_names)

        fts_query = _fts_or_query(title)
        if not fts_query:
            return []

        try:
            fts_rows = self._conn.execute(
                "SELECT question_id FROM search_index WHERE search_index MATCH ? AND entity_type = 'question' "
                "ORDER BY rank LIMIT ?",
                (fts_query, _CANDIDATE_LIMIT),
            ).fetchall()
        except sqlite3.OperationalError:
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

    def _filter_visible_matches(self, fts_rows: list[tuple]) -> list[tuple]:
        """Drop full-text matches on soft-deleted answers.

        Only rejected answers are removed, not pending ones. Whether an answer
        awaiting review should steer search is a separate question that
        predates soft-delete, and changing it here would quietly alter what
        agents find.
        """
        answer_ids = [r[0] for r in fts_rows if r[1] == "answer"]
        if not answer_ids:
            return list(fts_rows)
        placeholders = ",".join("?" for _ in answer_ids)
        rejected = {
            r[0]
            for r in self._conn.execute(
                f"SELECT id FROM answers WHERE id IN ({placeholders}) AND status = 'rejected'",
                answer_ids,
            ).fetchall()
        }
        return [r for r in fts_rows if r[1] != "answer" or r[0] not in rejected]

    def _get_question_tag_names(self, question_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT t.name FROM tags t JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ?",
            (question_id,),
        ).fetchall()
        return {r[0] for r in rows}

    def _refresh_question_fts(self, question_id: str) -> None:
        """Rebuild the FTS entry for a single question with current tag names."""
        q = self.get_question(question_id)
        if q is None:
            return
        self._conn.execute(
            "DELETE FROM search_index WHERE entity_id = ? AND entity_type = 'question'",
            (question_id,),
        )
        tag_text = " ".join(sorted(self._get_question_tag_names(question_id)))
        self._conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, "question", question_id, q.title, q.body, tag_text),
        )

    def get_status(self) -> dict[str, Any]:
        # A question still awaiting review is not part of the corpus yet, so
        # the headline counts treat it like a deleted one and it is reported
        # separately as pending_questions instead.
        total_questions = self._conn.execute(
            "SELECT COUNT(*) FROM questions WHERE status NOT IN ('deleted', 'pending')"
        ).fetchone()[0]
        total_answers = self._conn.execute("SELECT COUNT(*) FROM answers WHERE status = 'approved'").fetchone()[0]
        total_tags = self._conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        total_votes = self._conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
        unanswered = self._conn.execute(
            "SELECT COUNT(DISTINCT q.id) FROM questions q LEFT JOIN answers a ON a.question_id = q.id AND a.status = 'approved' WHERE a.id IS NULL AND q.status NOT IN ('deleted', 'pending')"
        ).fetchone()[0]
        pending_questions = self._conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'pending'").fetchone()[0]
        # Match pending_queue(): the dashboard count describes review cards,
        # not hidden children bundled under a pending or deleted question.
        pending_answers = self._conn.execute(
            "SELECT COUNT(*) FROM answers a JOIN questions q ON q.id = a.question_id"
            " WHERE a.status = 'pending' AND q.status IN ('open', 'resolved')"
        ).fetchone()[0]
        pending_comments = self._conn.execute(
            "SELECT COUNT(*) FROM comments c WHERE c.status = 'pending' AND ("
            " (c.parent_type = 'question' AND EXISTS (SELECT 1 FROM questions q"
            "   WHERE q.id = c.parent_id AND q.status IN ('open', 'resolved')))"
            " OR (c.parent_type = 'answer' AND EXISTS (SELECT 1 FROM answers a"
            "   JOIN questions q ON q.id = a.question_id WHERE a.id = c.parent_id"
            "   AND a.status = 'approved' AND q.status IN ('open', 'resolved'))))"
        ).fetchone()[0]
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
        """Export published content and moderation updates after *since*.

        Pending questions and their children stay server-side until approval.
        Besides avoiding orphan rows, this lets older clients synchronize while
        a mixed-version deployment is in progress because they never receive
        the new ``pending`` question status.
        """
        if since:
            questions = self._conn.execute(
                "SELECT data FROM questions WHERE status != 'pending' AND updated_at >= ? ORDER BY updated_at",
                (since,),
            ).fetchall()
            answers = self._conn.execute(
                "SELECT a.data FROM answers a JOIN questions q ON q.id = a.question_id"
                " WHERE q.status != 'pending' AND (a.updated_at >= ? OR q.updated_at >= ?)"
                " ORDER BY a.updated_at",
                (since, since),
            ).fetchall()
            votes = self._conn.execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM votes WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
            comments = self._conn.execute(
                "SELECT c.data FROM comments c LEFT JOIN answers a"
                " ON c.parent_type = 'answer' AND a.id = c.parent_id"
                " JOIN questions q ON q.id = CASE WHEN c.parent_type = 'question'"
                " THEN c.parent_id ELSE a.question_id END WHERE q.status != 'pending'"
                " AND (c.updated_at >= ? OR q.updated_at >= ? OR a.updated_at >= ?)"
                " ORDER BY c.updated_at",
                (since, since, since),
            ).fetchall()
        else:
            questions = self._conn.execute(
                "SELECT data FROM questions WHERE status != 'pending' ORDER BY created_at"
            ).fetchall()
            answers = self._conn.execute(
                "SELECT a.data FROM answers a JOIN questions q ON q.id = a.question_id"
                " WHERE q.status != 'pending' ORDER BY a.created_at"
            ).fetchall()
            votes = self._conn.execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM votes ORDER BY created_at"
            ).fetchall()
            comments = self._conn.execute(
                "SELECT c.data FROM comments c LEFT JOIN answers a"
                " ON c.parent_type = 'answer' AND a.id = c.parent_id"
                " JOIN questions q ON q.id = CASE WHEN c.parent_type = 'question'"
                " THEN c.parent_id ELSE a.question_id END"
                " WHERE q.status != 'pending' ORDER BY c.created_at"
            ).fetchall()

        tags = self._conn.execute("SELECT id, name, description, usage_count FROM tags ORDER BY name").fetchall()
        question_tags = self._conn.execute(
            "SELECT qt.question_id, qt.tag_id FROM question_tags qt JOIN questions q"
            " ON q.id = qt.question_id WHERE q.status != 'pending'"
        ).fetchall()

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
                    "created_at": r[6],
                }
                for r in votes
            ],
            "comments": [json.loads(r[0]) for r in comments],
        }

    def bulk_upsert(self, data: dict) -> int:
        """Import data dict (from export_since). Uses INSERT OR REPLACE. Returns count."""
        count = 0

        # Build tag-name lookup so we can populate FTS tags column.
        tag_names_by_id = {t["id"]: t["name"] for t in data.get("tags", [])}
        q_tag_map: dict[str, list[str]] = {}
        for qt in data.get("question_tags", []):
            name = tag_names_by_id.get(qt["tag_id"], "")
            if name:
                q_tag_map.setdefault(qt["question_id"], []).append(name)

        for q_data in data.get("questions", []):
            q = Question.model_validate(q_data)
            self._conn.execute(
                "INSERT OR REPLACE INTO questions (id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    q.id,
                    q.model_dump_json(),
                    q.status,
                    q.created_at.isoformat(),
                    q.updated_at.isoformat(),
                ),
            )
            # Upsert search index entry.
            self._conn.execute(
                "DELETE FROM search_index WHERE entity_id = ? AND entity_type = 'question'",
                (q.id,),
            )
            tag_text = " ".join(q_tag_map.get(q.id, []))
            self._conn.execute(
                "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (q.id, "question", q.id, q.title, q.body, tag_text),
            )
            count += 1

        for a_data in data.get("answers", []):
            a = Answer.model_validate(a_data)
            self._conn.execute(
                "INSERT OR REPLACE INTO answers (id, question_id, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
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
                "DELETE FROM search_index WHERE entity_id = ? AND entity_type = 'answer'",
                (a.id,),
            )
            self._conn.execute(
                "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (a.id, "answer", a.question_id, "", a.body, ""),
            )
            count += 1

        for t_data in data.get("tags", []):
            self._conn.execute(
                "INSERT OR REPLACE INTO tags (id, name, description, usage_count) VALUES (?, ?, ?, ?)",
                (t_data["id"], t_data["name"], t_data.get("description"), t_data.get("usage_count", 0)),
            )
            count += 1

        for qt_data in data.get("question_tags", []):
            self._conn.execute(
                "INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)",
                (qt_data["question_id"], qt_data["tag_id"]),
            )

        for v_data in data.get("votes", []):
            self._conn.execute(
                "INSERT OR IGNORE INTO votes (id, target_id, target_type, voter_id, voter_type, value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            self._conn.execute(
                "INSERT OR REPLACE INTO comments (id, parent_id, parent_type, data, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    c.id,
                    c.parent_id,
                    c.parent_type,
                    c.model_dump_json(),
                    c.status,
                    c.created_at.isoformat(),
                    c.updated_at.isoformat(),
                ),
            )
            count += 1

        self._conn.commit()
        return count

    # ------------------------------------------------------------------
    # Drain tracking
    # ------------------------------------------------------------------

    def mark_for_drain(self, entity_id: str, entity_type: str) -> None:
        """Mark a locally-created entity as needing drain to team API."""
        self._conn.execute(
            "INSERT OR IGNORE INTO pending_drain (entity_id, entity_type) VALUES (?, ?)",
            (entity_id, entity_type),
        )
        self._conn.commit()

    def get_pending_drain(self) -> list[dict]:
        """Return all entities pending drain, grouped by type."""
        rows = self._conn.execute("SELECT entity_id, entity_type FROM pending_drain ORDER BY created_at").fetchall()
        return [{"entity_id": r[0], "entity_type": r[1]} for r in rows]

    def clear_drain(self, entity_id: str) -> None:
        """Remove an entity from the pending drain queue after successful push."""
        self._conn.execute("DELETE FROM pending_drain WHERE entity_id = ?", (entity_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Agent keys
    # ------------------------------------------------------------------

    def create_agent_key(self, api_key: str, agent_name: str, github_username: str) -> dict:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO agent_keys (api_key, agent_name, github_username, created_at) VALUES (?, ?, ?, ?)",
            (api_key, agent_name, github_username, now),
        )
        self._conn.commit()
        return {"api_key": api_key, "agent_name": agent_name, "github_username": github_username, "created_at": now}

    def get_agent_key(self, api_key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT api_key, agent_name, github_username, created_at FROM agent_keys WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        if row is None:
            return None
        return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

    def get_agent_key_by_github(self, github_username: str) -> dict | None:
        row = self._conn.execute(
            "SELECT api_key, agent_name, github_username, created_at FROM agent_keys WHERE github_username = ?",
            (github_username,),
        ).fetchone()
        if row is None:
            return None
        return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

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
        edited_at=datetime.fromisoformat(row[7]),
    )
