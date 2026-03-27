"""PostgreSQL schema for the acq shared store.

Mirrors sqlite_schema.py but uses Postgres types, dogpark schema prefix,
and tsvector columns with GIN indexes for full-text search.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

_DDL = """
CREATE SCHEMA IF NOT EXISTS dogpark;

CREATE TABLE IF NOT EXISTS dogpark.questions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    search_vector tsvector
);

CREATE TABLE IF NOT EXISTS dogpark.answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES dogpark.questions(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    search_vector tsvector
);

CREATE TABLE IF NOT EXISTS dogpark.comments (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    parent_type TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dogpark.votes (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    voter_type TEXT NOT NULL,
    value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(target_id, voter_id, voter_type)
);

CREATE TABLE IF NOT EXISTS dogpark.tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dogpark.question_tags (
    question_id TEXT NOT NULL REFERENCES dogpark.questions(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES dogpark.tags(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_question_tags_tag ON dogpark.question_tags(tag_id);

CREATE TABLE IF NOT EXISTS dogpark.edit_history (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    previous_body TEXT NOT NULL,
    new_body TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    edited_by_type TEXT NOT NULL,
    edited_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dogpark.schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dogpark.users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

-- GIN indexes for tsvector full-text search
CREATE INDEX IF NOT EXISTS idx_questions_search_vector
    ON dogpark.questions USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS idx_answers_search_vector
    ON dogpark.answers USING GIN (search_vector);
"""


def create_tables(conn) -> None:
    """Execute DDL to create the dogpark schema and all tables.

    *conn* must be a psycopg2 connection (or compatible).
    """
    cur = conn.cursor()
    cur.execute(_DDL)
    cur.execute("SELECT version FROM dogpark.schema_version")
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO dogpark.schema_version (version) VALUES (%s)",
            (SCHEMA_VERSION,),
        )
    conn.commit()
    cur.close()
