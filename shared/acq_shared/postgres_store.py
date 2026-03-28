"""PostgresStore — Postgres-backed Store implementation.

Mirrors SqliteStore method-for-method but uses psycopg2, ``dogpark.`` schema
prefix, and tsvector columns for full-text search instead of FTS5.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg2

from acq_shared.models import Answer, Comment, EditHistory, Question, Tag, Vote
from acq_shared.postgres_schema import create_tables
from acq_shared.scoring import rank_answers, search_content_score, text_relevance_score


class PostgresStore:
    """Postgres-backed store implementing the Store protocol.

    Constructor takes a psycopg2 connection and calls ``create_tables()``
    to ensure the ``dogpark`` schema exists.
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
        """Replace the connection using the connect factory, if available."""
        if self._connect is None:
            raise
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = self._connect()

    def _execute(self, sql: str, params: tuple = ()) -> Any:
        with self._lock:
            try:
                cur = self._conn.cursor()
                cur.execute(sql, params)
                return cur
            except Exception:
                # Connection may be stale (e.g., JWT expired). Reconnect and retry once.
                if self._connect is None:
                    raise
                self._reconnect()
                cur = self._conn.cursor()
                cur.execute(sql, params)
                return cur

    def _execute_returning(self, sql: str, params: tuple = ()) -> Any:
        cur = self._execute(sql, params)
        return cur

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, username: str, password_hash: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._execute(
            "INSERT INTO dogpark.users (username, password_hash, created_at) VALUES (%s, %s, %s)",
            (username, password_hash, now),
        )
        self._conn.commit()

    def get_user(self, username: str) -> dict[str, str] | None:
        cur = self._execute(
            "SELECT username, password_hash, created_at FROM dogpark.users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"username": row[0], "password_hash": row[1], "created_at": str(row[2])}

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def get_or_create_tag(self, name: str) -> Tag:
        tag = Tag(name=name)
        cur = self._execute(
            "SELECT id, name, description, usage_count FROM dogpark.tags WHERE name = %s",
            (tag.name,),
        )
        row = cur.fetchone()
        if row is not None:
            return Tag(id=row[0], name=row[1], description=row[2], usage_count=row[3])
        self._execute(
            "INSERT INTO dogpark.tags (id, name, description, usage_count) VALUES (%s, %s, %s, %s)",
            (tag.id, tag.name, tag.description, tag.usage_count),
        )
        self._conn.commit()
        return tag

    def merge_tags(self, source_id: str, target_id: str) -> None:
        # Collect affected questions before the merge so we can refresh tsvectors.
        cur = self._execute(
            "SELECT question_id FROM dogpark.question_tags WHERE tag_id = %s OR tag_id = %s",
            (source_id, target_id),
        )
        affected_qids = {r[0] for r in cur.fetchall()}

        self._execute(
            """
            UPDATE dogpark.question_tags SET tag_id = %s
            WHERE tag_id = %s
              AND question_id NOT IN (
                  SELECT question_id FROM dogpark.question_tags WHERE tag_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        self._execute("DELETE FROM dogpark.question_tags WHERE tag_id = %s", (source_id,))
        self._execute("DELETE FROM dogpark.tags WHERE id = %s", (source_id,))
        cur = self._execute("SELECT COUNT(*) FROM dogpark.question_tags WHERE tag_id = %s", (target_id,))
        row = cur.fetchone()
        self._execute("UPDATE dogpark.tags SET usage_count = %s WHERE id = %s", (row[0], target_id))

        # Refresh tsvectors for affected questions.
        for qid in affected_qids:
            self._refresh_question_tsvector(qid)

        self._conn.commit()

    def list_tags(self, q: str | None = None) -> list[Tag]:
        if q:
            cur = self._execute(
                "SELECT id, name, description, usage_count FROM dogpark.tags WHERE name LIKE %s",
                (f"%{q}%",),
            )
        else:
            cur = self._execute("SELECT id, name, description, usage_count FROM dogpark.tags ORDER BY usage_count DESC")
        rows = cur.fetchall()
        return [Tag(id=r[0], name=r[1], description=r[2], usage_count=r[3]) for r in rows]

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def create_question(self, question: Question, tag_names: list[str]) -> Question:
        self._execute(
            "INSERT INTO dogpark.questions (id, data, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            (
                question.id,
                question.model_dump_json(),
                question.status,
                question.created_at.isoformat(),
                question.updated_at.isoformat(),
            ),
        )
        tags = [self.get_or_create_tag(name) for name in tag_names]
        for tag in tags:
            self._execute(
                "INSERT INTO dogpark.question_tags (question_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (question.id, tag.id),
            )
            self._execute("UPDATE dogpark.tags SET usage_count = usage_count + 1 WHERE id = %s", (tag.id,))
        # Update tsvector with title + body + tag names.
        tag_text = " ".join(t.name for t in tags)
        self._execute(
            "UPDATE dogpark.questions SET search_vector ="
            " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
            (question.title, question.body, tag_text, question.id),
        )
        self._conn.commit()
        return question

    def get_question(self, question_id: str) -> Question | None:
        cur = self._execute("SELECT data FROM dogpark.questions WHERE id = %s", (question_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Question.model_validate_json(row[0])

    def edit_question(self, question_id: str, new_body: str, edited_by: str, edited_by_type: str) -> Question | None:
        q = self.get_question(question_id)
        if q is None:
            return None
        history = EditHistory(
            target_id=question_id,
            target_type="question",
            previous_body=q.body,
            new_body=new_body,
            edited_by=edited_by,
            edited_by_type=edited_by_type,
        )
        self._execute(
            "INSERT INTO dogpark.edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
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
        updated = q.model_copy(update={"body": new_body, "updated_at": now})
        self._execute(
            "UPDATE dogpark.questions SET data = %s, updated_at = %s WHERE id = %s",
            (updated.model_dump_json(), now.isoformat(), question_id),
        )
        # Refresh tsvector with title + body + tag names.
        tag_text = " ".join(sorted(self._get_question_tag_names(question_id)))
        self._execute(
            "UPDATE dogpark.questions SET search_vector ="
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
            "UPDATE dogpark.questions SET data = %s WHERE id = %s",
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
            "UPDATE dogpark.questions SET data = %s WHERE id = %s",
            (updated.model_dump_json(), question_id),
        )
        self._conn.commit()
        return updated

    def get_question_history(self, question_id: str) -> list[EditHistory]:
        cur = self._execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM dogpark.edit_history WHERE target_id = %s AND target_type = 'question' ORDER BY edited_at ASC",
            (question_id,),
        )
        rows = cur.fetchall()
        return [_row_to_edit_history(r) for r in rows]

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
        if tag is not None:
            join = " JOIN dogpark.question_tags qt ON q.id = qt.question_id JOIN dogpark.tags t ON qt.tag_id = t.id"
            where_clauses.append("t.name = %s")
            params.append(tag)

        where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_select = "COUNT(DISTINCT q.id)" if tag is not None else "COUNT(*)"
        total = self._execute(
            f"SELECT {count_select} FROM dogpark.questions q{join}{where}", tuple(params)
        ).fetchone()[0]

        rows = self._execute(
            f"SELECT q.data FROM dogpark.questions q{join}{where} ORDER BY q.created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()

        results: list[dict] = []
        for (data_json,) in rows:
            q = Question.model_validate_json(data_json)
            tag_names = self._get_question_tag_names(q.id)
            tags = [{"name": n} for n in sorted(tag_names)]
            answer_count = self._execute(
                "SELECT COUNT(*) FROM dogpark.answers WHERE question_id = %s AND status IN ('approved', 'pending')",
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
            "INSERT INTO dogpark.answers (id, question_id, data, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
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
            "UPDATE dogpark.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
            (answer.body, answer.id),
        )
        self._conn.commit()
        return answer

    def get_answer(self, answer_id: str) -> Answer | None:
        cur = self._execute("SELECT data FROM dogpark.answers WHERE id = %s", (answer_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return Answer.model_validate_json(row[0])

    def edit_answer(self, answer_id: str, new_body: str, edited_by: str, edited_by_type: str) -> Answer | None:
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
            "INSERT INTO dogpark.edit_history (id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
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
            "UPDATE dogpark.answers SET data = %s, updated_at = %s WHERE id = %s",
            (updated.model_dump_json(), now.isoformat(), answer_id),
        )
        # Refresh tsvector
        self._execute(
            "UPDATE dogpark.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
            (updated.body, answer_id),
        )
        self._conn.commit()
        return updated

    def get_answer_history(self, answer_id: str) -> list[EditHistory]:
        cur = self._execute(
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM dogpark.edit_history WHERE target_id = %s AND target_type = 'answer' ORDER BY edited_at ASC",
            (answer_id,),
        )
        rows = cur.fetchall()
        return [_row_to_edit_history(r) for r in rows]

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def create_comment(self, comment: Comment) -> Comment:
        self._execute(
            "INSERT INTO dogpark.comments (id, parent_id, parent_type, data, status, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
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

    # ------------------------------------------------------------------
    # Votes
    # ------------------------------------------------------------------

    def cast_vote(self, vote: Vote) -> dict[str, Any]:
        cur = self._execute(
            "SELECT created_at FROM dogpark.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
            (vote.target_id, vote.voter_id, vote.voter_type),
        )
        existing = cur.fetchone()
        if existing is not None:
            return {"error": "duplicate_vote"}

        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        cur = self._execute(
            "SELECT created_at FROM dogpark.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s AND created_at >= %s",
            (vote.target_id, vote.voter_id, vote.voter_type, cutoff),
        )
        recent = cur.fetchone()
        if recent is not None:
            return {"error": "rate_limited"}

        try:
            self._execute(
                "INSERT INTO dogpark.votes (id, target_id, target_type, voter_id, voter_type, value, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
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
            "SELECT voter_type, value, COUNT(*) FROM dogpark.votes WHERE target_id = %s GROUP BY voter_type, value",
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
            cur = self._execute("SELECT data FROM dogpark.questions WHERE id = %s", (target_id,))
            data_row = cur.fetchone()
            if data_row:
                q = Question.model_validate_json(data_row[0])
                updated = q.model_copy(update=counts)
                self._execute(
                    "UPDATE dogpark.questions SET data = %s WHERE id = %s",
                    (updated.model_dump_json(), target_id),
                )
        elif target_type == "answer":
            cur = self._execute("SELECT data FROM dogpark.answers WHERE id = %s", (target_id,))
            data_row = cur.fetchone()
            if data_row:
                a = Answer.model_validate_json(data_row[0])
                updated = a.model_copy(update=counts)
                self._execute(
                    "UPDATE dogpark.answers SET data = %s WHERE id = %s",
                    (updated.model_dump_json(), target_id),
                )
        return counts

    def delete_vote(self, target_id: str, voter_id: str, voter_type: str) -> bool:
        cur = self._execute(
            "SELECT target_type FROM dogpark.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
            (target_id, voter_id, voter_type),
        )
        row = cur.fetchone()
        if row is None:
            return False
        target_type = row[0]
        self._execute(
            "DELETE FROM dogpark.votes WHERE target_id = %s AND voter_id = %s AND voter_type = %s",
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
            f"SELECT target_id, value FROM dogpark.votes WHERE voter_id = %s AND voter_type = %s AND target_id IN ({placeholders})",
            (voter_id, voter_type, *target_ids),
        )
        return {r[0]: r[1] for r in cur.fetchall()}

    # ------------------------------------------------------------------
    # Moderation
    # ------------------------------------------------------------------

    def approve_content(self, content_id: str) -> bool:
        for table in ("answers", "comments"):
            cur = self._execute(f"SELECT data, status FROM dogpark.{table} WHERE id = %s", (content_id,))
            row = cur.fetchone()
            if row is not None:
                if row[1] != "pending":
                    return False
                if table == "answers":
                    obj = Answer.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "approved"})
                    self._execute(
                        "UPDATE dogpark.answers SET data = %s, status = 'approved' WHERE id = %s",
                        (updated.model_dump_json(), content_id),
                    )
                else:
                    obj = Comment.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "approved"})
                    self._execute(
                        "UPDATE dogpark.comments SET data = %s, status = 'approved' WHERE id = %s",
                        (updated.model_dump_json(), content_id),
                    )
                self._conn.commit()
                return True
        return False

    def reject_content(self, content_id: str) -> bool:
        for table in ("answers", "comments"):
            cur = self._execute(f"SELECT data, status FROM dogpark.{table} WHERE id = %s", (content_id,))
            row = cur.fetchone()
            if row is not None:
                if row[1] != "pending":
                    return False
                if table == "answers":
                    obj = Answer.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "rejected"})
                    self._execute(
                        "UPDATE dogpark.answers SET data = %s, status = 'rejected' WHERE id = %s",
                        (updated.model_dump_json(), content_id),
                    )
                else:
                    obj = Comment.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "rejected"})
                    self._execute(
                        "UPDATE dogpark.comments SET data = %s, status = 'rejected' WHERE id = %s",
                        (updated.model_dump_json(), content_id),
                    )
                self._conn.commit()
                return True
        return False

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def pending_queue(self) -> dict[str, list[Any]]:
        cur = self._execute("SELECT data FROM dogpark.answers WHERE status = 'pending' ORDER BY created_at ASC")
        answer_rows = cur.fetchall()
        cur = self._execute("SELECT data FROM dogpark.comments WHERE status = 'pending' ORDER BY created_at ASC")
        comment_rows = cur.fetchall()
        return {
            "answers": [Answer.model_validate_json(r[0]) for r in answer_rows],
            "comments": [Comment.model_validate_json(r[0]) for r in comment_rows],
        }

    def get_question_thread(self, question_id: str, include_pending: bool = False) -> dict[str, Any] | None:
        q = self.get_question(question_id)
        if q is None:
            return None

        if include_pending:
            cur = self._execute(
                "SELECT data FROM dogpark.answers WHERE question_id = %s AND status IN ('approved', 'pending')",
                (question_id,),
            )
            answer_rows = cur.fetchall()
            all_answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
            approved = [a for a in all_answers if a.status == "approved"]
            pending = [a for a in all_answers if a.status == "pending"]
            ranked = rank_answers(approved, q.pinned_answer_id) + pending
        else:
            cur = self._execute(
                "SELECT data FROM dogpark.answers WHERE question_id = %s AND status = 'approved'",
                (question_id,),
            )
            answer_rows = cur.fetchall()
            ranked = rank_answers(
                [Answer.model_validate_json(r[0]) for r in answer_rows],
                q.pinned_answer_id,
            )

        cur = self._execute(
            "SELECT data FROM dogpark.comments WHERE parent_id = %s AND parent_type = 'question' AND status = 'approved'",
            (question_id,),
        )
        comment_rows = cur.fetchall()
        q_comments = [Comment.model_validate_json(r[0]) for r in comment_rows]

        answer_threads = []
        for answer in ranked:
            cur = self._execute(
                "SELECT data FROM dogpark.comments WHERE parent_id = %s AND parent_type = 'answer' AND status = 'approved'",
                (answer.id,),
            )
            a_comment_rows = cur.fetchall()
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
        """Tsvector + tag Jaccard search returning ranked question threads."""
        query_tags = set(tags or [])

        words = query.strip().split()
        if not words:
            return []
        tsquery_str = " | ".join(w for w in words if w)

        try:
            # Search questions
            cur = self._execute(
                """
                SELECT id, ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM dogpark.questions
                WHERE search_vector @@ to_tsquery('english', %s)
                """,
                (tsquery_str, tsquery_str),
            )
            q_rows = cur.fetchall()

            # Search answers
            cur = self._execute(
                """
                SELECT question_id, ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM dogpark.answers
                WHERE search_vector @@ to_tsquery('english', %s)
                """,
                (tsquery_str, tsquery_str),
            )
            a_rows = cur.fetchall()
        except Exception:
            self._conn.rollback()
            return []

        # Collect best rank per question
        best_rank_per_question: dict[str, float] = {}
        for qid, rank in q_rows:
            current = best_rank_per_question.get(qid)
            if current is None or rank > current:
                best_rank_per_question[qid] = rank
        for qid, rank in a_rows:
            current = best_rank_per_question.get(qid)
            if current is None or rank > current:
                best_rank_per_question[qid] = rank

        if not best_rank_per_question:
            return []

        raw_ranks = list(best_rank_per_question.values())
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        scored: list[tuple[float, str]] = []
        for question_id, raw_rank in best_rank_per_question.items():
            q = self.get_question(question_id)
            if q is None:
                continue

            normalized_rank = (raw_rank - min_rank) / rank_range

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
                "SELECT data FROM dogpark.answers WHERE question_id = %s AND status = 'approved'",
                (question_id,),
            )
            answer_rows = cur.fetchall()
            answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
            ranked_answers = rank_answers(answers, q.pinned_answer_id)
            best_answer = ranked_answers[0] if ranked_answers else None

            content_score = search_content_score(q, best_answer)
            final_score = text_rel * (1.0 + content_score)

            scored.append((final_score, question_id))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        results = []
        for _, question_id in scored:
            thread = self.get_question_thread(question_id)
            if thread is None:
                continue
            thread["answers"] = thread["answers"][:3]
            results.append(thread)

        return results

    def find_similar_questions(self, title: str, tag_names: list[str]) -> list[dict[str, Any]]:
        """Tsvector on title field, Jaccard on tags, threshold 0.5, return top 3."""
        query_tags = set(tag_names)

        words = title.strip().split()
        if not words:
            return []
        tsquery_str = " | ".join(w for w in words if w)

        try:
            cur = self._execute(
                """
                SELECT id, ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM dogpark.questions
                WHERE search_vector @@ to_tsquery('english', %s)
                """,
                (tsquery_str, tsquery_str),
            )
            fts_rows = cur.fetchall()
        except Exception:
            self._conn.rollback()
            return []

        if not fts_rows:
            return []

        raw_ranks = [r[1] for r in fts_rows]
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        scored = []
        for question_id, raw_rank in fts_rows:
            q = self.get_question(question_id)
            if q is None:
                continue

            normalized_rank = (raw_rank - min_rank) / rank_range

            q_tags = self._get_question_tag_names(question_id)
            if query_tags or q_tags:
                intersection = len(query_tags & q_tags)
                union = len(query_tags | q_tags)
                jaccard = intersection / union if union > 0 else 0.0
            else:
                jaccard = 0.0

            similarity = 0.5 * normalized_rank + 0.5 * jaccard

            if similarity >= 0.5:
                scored.append((similarity, q))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"question": q, "similarity": score} for score, q in scored[:3]]

    def _get_question_tag_names(self, question_id: str) -> set[str]:
        cur = self._execute(
            "SELECT t.name FROM dogpark.tags t JOIN dogpark.question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = %s",
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
            "UPDATE dogpark.questions SET search_vector ="
            " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
            (q.title, q.body, tag_text, question_id),
        )

    def get_status(self) -> dict[str, Any]:
        total_questions = self._execute("SELECT COUNT(*) FROM dogpark.questions").fetchone()[0]
        total_answers = self._execute("SELECT COUNT(*) FROM dogpark.answers WHERE status = 'approved'").fetchone()[0]
        total_tags = self._execute("SELECT COUNT(*) FROM dogpark.tags").fetchone()[0]
        total_votes = self._execute("SELECT COUNT(*) FROM dogpark.votes").fetchone()[0]
        unanswered = self._execute(
            "SELECT COUNT(DISTINCT q.id) FROM dogpark.questions q LEFT JOIN dogpark.answers a ON a.question_id = q.id AND a.status = 'approved' WHERE a.id IS NULL"
        ).fetchone()[0]
        pending_answers = self._execute("SELECT COUNT(*) FROM dogpark.answers WHERE status = 'pending'").fetchone()[0]
        pending_comments = self._execute("SELECT COUNT(*) FROM dogpark.comments WHERE status = 'pending'").fetchone()[0]
        return {
            "total_questions": total_questions,
            "total_answers": total_answers,
            "total_tags": total_tags,
            "total_votes": total_votes,
            "unanswered": unanswered,
            "pending": pending_answers + pending_comments,
        }

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_since(self, since: str | None = None) -> dict:
        if since:
            questions = self._execute(
                "SELECT data FROM dogpark.questions WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            answers = self._execute(
                "SELECT data FROM dogpark.answers WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            votes = self._execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM dogpark.votes WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
            comments = self._execute(
                "SELECT data FROM dogpark.comments WHERE created_at >= %s ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            questions = self._execute("SELECT data FROM dogpark.questions ORDER BY created_at").fetchall()
            answers = self._execute("SELECT data FROM dogpark.answers ORDER BY created_at").fetchall()
            votes = self._execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM dogpark.votes ORDER BY created_at"
            ).fetchall()
            comments = self._execute("SELECT data FROM dogpark.comments ORDER BY created_at").fetchall()

        tags = self._execute("SELECT id, name, description, usage_count FROM dogpark.tags ORDER BY name").fetchall()
        question_tags = self._execute("SELECT question_id, tag_id FROM dogpark.question_tags").fetchall()

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
                INSERT INTO dogpark.questions (id, data, status, created_at, updated_at)
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
                "UPDATE dogpark.questions SET search_vector ="
                " to_tsvector('english', %s || ' ' || %s || ' ' || %s) WHERE id = %s",
                (q.title, q.body, tag_text, q.id),
            )
            count += 1

        for a_data in data.get("answers", []):
            a = Answer.model_validate(a_data)
            self._execute(
                """
                INSERT INTO dogpark.answers (id, question_id, data, status, created_at, updated_at)
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
                "UPDATE dogpark.answers SET search_vector = to_tsvector('english', %s) WHERE id = %s",
                (a.body, a.id),
            )
            count += 1

        for t_data in data.get("tags", []):
            self._execute(
                """
                INSERT INTO dogpark.tags (id, name, description, usage_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                    usage_count = EXCLUDED.usage_count
                """,
                (t_data["id"], t_data["name"], t_data.get("description"), t_data.get("usage_count", 0)),
            )
            count += 1

        for qt_data in data.get("question_tags", []):
            self._execute(
                "INSERT INTO dogpark.question_tags (question_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (qt_data["question_id"], qt_data["tag_id"]),
            )

        for v_data in data.get("votes", []):
            self._execute(
                """
                INSERT INTO dogpark.votes (id, target_id, target_type, voter_id, voter_type, value, created_at)
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
                INSERT INTO dogpark.comments (id, parent_id, parent_type, data, status, created_at)
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
