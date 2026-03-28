"""SqliteStore — shared SQLite-backed Store implementation.

Satisfies the Store protocol defined in acq_shared.store. Uses FTS5 for
full-text search, WAL mode for concurrency, and stores model data as
JSON blobs alongside indexed columns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from acq_shared.models import Answer, Comment, EditHistory, Question, Tag, Vote
from acq_shared.scoring import rank_answers, search_content_score, search_score, text_relevance_score
from acq_shared.sqlite_schema import create_tables


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
        self._conn.commit()
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
        tags = [self.get_or_create_tag(name) for name in tag_names]
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
        updated = q.model_copy(update={"body": new_body, "updated_at": now})
        self._conn.execute(
            "UPDATE questions SET data = ?, updated_at = ? WHERE id = ?",
            (updated.model_dump_json(), now.isoformat(), question_id),
        )
        self._conn.execute(
            "DELETE FROM search_index WHERE entity_id = ? AND entity_type = 'question'",
            (question_id,),
        )
        tag_text = " ".join(sorted(self._get_question_tag_names(question_id)))
        self._conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, "question", question_id, updated.title, updated.body, tag_text),
        )
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
            "SELECT id, target_id, target_type, previous_body, new_body, edited_by, edited_by_type, edited_at FROM edit_history WHERE target_id = ? AND target_type = 'question' ORDER BY edited_at ASC",
            (question_id,),
        ).fetchall()
        return [_row_to_edit_history(r) for r in rows]

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
            "INSERT INTO comments (id, parent_id, parent_type, data, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
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

    # ------------------------------------------------------------------
    # Moderation
    # ------------------------------------------------------------------

    def approve_content(self, content_id: str) -> bool:
        for table in ("answers", "comments"):
            row = self._conn.execute(f"SELECT data, status FROM {table} WHERE id = ?", (content_id,)).fetchone()
            if row is not None:
                if row[1] != "pending":
                    return False
                if table == "answers":
                    obj = Answer.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "approved"})
                    self._conn.execute(
                        "UPDATE answers SET data = ?, status = 'approved' WHERE id = ?",
                        (updated.model_dump_json(), content_id),
                    )
                else:
                    obj = Comment.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "approved"})
                    self._conn.execute(
                        "UPDATE comments SET data = ?, status = 'approved' WHERE id = ?",
                        (updated.model_dump_json(), content_id),
                    )
                self._conn.commit()
                return True
        return False

    def reject_content(self, content_id: str) -> bool:
        for table in ("answers", "comments"):
            row = self._conn.execute(f"SELECT data, status FROM {table} WHERE id = ?", (content_id,)).fetchone()
            if row is not None:
                if row[1] != "pending":
                    return False
                if table == "answers":
                    obj = Answer.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "rejected"})
                    self._conn.execute(
                        "UPDATE answers SET data = ?, status = 'rejected' WHERE id = ?",
                        (updated.model_dump_json(), content_id),
                    )
                else:
                    obj = Comment.model_validate_json(row[0])
                    updated = obj.model_copy(update={"status": "rejected"})
                    self._conn.execute(
                        "UPDATE comments SET data = ?, status = 'rejected' WHERE id = ?",
                        (updated.model_dump_json(), content_id),
                    )
                self._conn.commit()
                return True
        return False

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def pending_queue(self) -> dict[str, list[Any]]:
        answer_rows = self._conn.execute(
            "SELECT data FROM answers WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        comment_rows = self._conn.execute(
            "SELECT data FROM comments WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return {
            "answers": [Answer.model_validate_json(r[0]) for r in answer_rows],
            "comments": [Comment.model_validate_json(r[0]) for r in comment_rows],
        }

    def get_question_thread(self, question_id: str) -> dict[str, Any] | None:
        q = self.get_question(question_id)
        if q is None:
            return None

        answer_rows = self._conn.execute(
            "SELECT data FROM answers WHERE question_id = ? AND status = 'approved'",
            (question_id,),
        ).fetchall()
        answers = [Answer.model_validate_json(r[0]) for r in answer_rows]
        ranked = rank_answers(answers, q.pinned_answer_id)

        comment_rows = self._conn.execute(
            "SELECT data FROM comments WHERE parent_id = ? AND parent_type = 'question' AND status = 'approved'",
            (question_id,),
        ).fetchall()
        q_comments = [Comment.model_validate_json(r[0]) for r in comment_rows]

        answer_threads = []
        for answer in ranked:
            a_comment_rows = self._conn.execute(
                "SELECT data FROM comments WHERE parent_id = ? AND parent_type = 'answer' AND status = 'approved'",
                (answer.id,),
            ).fetchall()
            a_comments = [Comment.model_validate_json(r[0]) for r in a_comment_rows]
            answer_threads.append({"answer": answer, "comments": a_comments})

        tag_names = sorted(self._get_question_tag_names(question_id))
        return {
            "question": q,
            "tags": tag_names,
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

        words = query.strip().split()
        fts_query = " OR ".join(w for w in words if w)
        try:
            fts_rows = self._conn.execute(
                "SELECT entity_id, entity_type, question_id, rank FROM search_index WHERE search_index MATCH ? ORDER BY rank",
                (fts_query,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        if not fts_rows:
            return []

        raw_ranks = [r[3] for r in fts_rows]
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        best_rank_per_question: dict[str, float] = {}
        for entity_id, entity_type, question_id, rank in fts_rows:
            current = best_rank_per_question.get(question_id)
            if current is None or rank < current:
                best_rank_per_question[question_id] = rank

        scored: list[tuple[float, str]] = []
        for question_id, raw_rank in best_rank_per_question.items():
            q = self.get_question(question_id)
            if q is None:
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
                text_relevance=text_rel, question=q, best_answer=best_answer,
            )

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
        """FTS5 on title field, Jaccard on tags, threshold 0.5, return top 3."""
        query_tags = set(tag_names)

        try:
            fts_rows = self._conn.execute(
                "SELECT entity_id, entity_type, question_id, rank FROM search_index WHERE search_index MATCH ? AND entity_type = 'question' ORDER BY rank",
                (title,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        if not fts_rows:
            return []

        raw_ranks = [r[3] for r in fts_rows]
        min_rank = min(raw_ranks)
        max_rank = max(raw_ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        scored = []
        for entity_id, entity_type, question_id, raw_rank in fts_rows:
            q = self.get_question(question_id)
            if q is None:
                continue

            normalized_rank = 1.0 - (raw_rank - min_rank) / rank_range

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
        total_questions = self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        total_answers = self._conn.execute("SELECT COUNT(*) FROM answers WHERE status = 'approved'").fetchone()[0]
        total_tags = self._conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        total_votes = self._conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
        unanswered = self._conn.execute(
            "SELECT COUNT(DISTINCT q.id) FROM questions q LEFT JOIN answers a ON a.question_id = q.id AND a.status = 'approved' WHERE a.id IS NULL"
        ).fetchone()[0]
        pending_answers = self._conn.execute("SELECT COUNT(*) FROM answers WHERE status = 'pending'").fetchone()[0]
        pending_comments = self._conn.execute("SELECT COUNT(*) FROM comments WHERE status = 'pending'").fetchone()[0]
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
        """Export all content, optionally filtered to items created after *since*."""
        if since:
            questions = self._conn.execute(
                "SELECT data FROM questions WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
            answers = self._conn.execute(
                "SELECT data FROM answers WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
            votes = self._conn.execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM votes WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
            comments = self._conn.execute(
                "SELECT data FROM comments WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            questions = self._conn.execute("SELECT data FROM questions ORDER BY created_at").fetchall()
            answers = self._conn.execute("SELECT data FROM answers ORDER BY created_at").fetchall()
            votes = self._conn.execute(
                "SELECT id, target_id, target_type, voter_id, voter_type, value, created_at FROM votes ORDER BY created_at"
            ).fetchall()
            comments = self._conn.execute("SELECT data FROM comments ORDER BY created_at").fetchall()

        tags = self._conn.execute("SELECT id, name, description, usage_count FROM tags ORDER BY name").fetchall()
        question_tags = self._conn.execute("SELECT question_id, tag_id FROM question_tags").fetchall()

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
                "INSERT OR REPLACE INTO comments (id, parent_id, parent_type, data, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
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
