from __future__ import annotations

import json
import sqlite3

SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    parent_type TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS votes (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    voter_type TEXT NOT NULL,
    value INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(target_id, voter_id, voter_type)
);

CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS question_tags (
    question_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (question_id, tag_id),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_question_tags_tag ON question_tags(tag_id);

CREATE TABLE IF NOT EXISTS edit_history (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    previous_body TEXT NOT NULL,
    new_body TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    edited_by_type TEXT NOT NULL,
    edited_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- Tracks IDs of locally-created content that needs to be drained to the
-- team API. Content pulled from team via bulk_upsert is NOT added here.
-- Drain removes entries after successful push.
CREATE TABLE IF NOT EXISTS pending_drain (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    entity_id UNINDEXED,
    entity_type UNINDEXED,
    question_id UNINDEXED,
    title,
    body,
    tags,
    tokenize='porter unicode61'
);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")

    # Detect current schema version before running DDL.
    current_version = 0
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is not None:
            current_version = row[0]
    except sqlite3.OperationalError:
        pass  # table doesn't exist yet — fresh install

    # v1→v2: FTS5 table gains a `tags` column. Virtual tables can't be
    # ALTERed, so drop and let the DDL recreate with the new schema.
    if current_version == 1:
        conn.execute("DROP TABLE IF EXISTS search_index")

    conn.executescript(_DDL)

    existing = conn.execute("SELECT version FROM schema_version").fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
    elif existing[0] < SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    # Rebuild FTS5 index after migration so existing rows include tags.
    if current_version == 1:
        _rebuild_fts_index(conn)

    conn.commit()


def _rebuild_fts_index(conn: sqlite3.Connection) -> None:
    """Re-populate the FTS5 search_index from questions and answers."""
    # Questions — include their tag names.
    q_rows = conn.execute("SELECT id, data FROM questions").fetchall()
    for qid, data_json in q_rows:
        data = json.loads(data_json)
        title = data.get("title", "")
        body = data.get("body", "")
        tag_rows = conn.execute(
            "SELECT t.name FROM tags t JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ?",
            (qid,),
        ).fetchall()
        tag_text = " ".join(r[0] for r in tag_rows)
        conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (qid, "question", qid, title, body, tag_text),
        )

    # Answers — no tags column content.
    a_rows = conn.execute("SELECT id, question_id, data FROM answers").fetchall()
    for aid, qid, data_json in a_rows:
        data = json.loads(data_json)
        body = data.get("body", "")
        conn.execute(
            "INSERT INTO search_index (entity_id, entity_type, question_id, title, body, tags) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (aid, "answer", qid, "", body, ""),
        )
