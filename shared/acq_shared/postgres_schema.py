"""PostgreSQL schema for the acq shared store.

Mirrors sqlite_schema.py but uses Postgres types, acq schema prefix,
and tsvector columns with GIN indexes for full-text search.
"""

from __future__ import annotations

SCHEMA_VERSION = 3

_DDL = """
CREATE SCHEMA IF NOT EXISTS acq;

CREATE TABLE IF NOT EXISTS acq.questions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    search_vector tsvector
);

CREATE TABLE IF NOT EXISTS acq.answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES acq.questions(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    search_vector tsvector
);

CREATE TABLE IF NOT EXISTS acq.comments (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    parent_type TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS acq.votes (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    voter_type TEXT NOT NULL,
    value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(target_id, voter_id, voter_type)
);

CREATE TABLE IF NOT EXISTS acq.tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS acq.question_tags (
    question_id TEXT NOT NULL REFERENCES acq.questions(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES acq.tags(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_question_tags_tag ON acq.question_tags(tag_id);

CREATE TABLE IF NOT EXISTS acq.edit_history (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    previous_body TEXT NOT NULL,
    new_body TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    edited_by_type TEXT NOT NULL,
    edited_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS acq.schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS acq.users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS acq.agent_keys (
    id SERIAL PRIMARY KEY,
    api_key TEXT NOT NULL UNIQUE,
    agent_name TEXT NOT NULL UNIQUE,
    github_username TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);

-- GIN indexes for tsvector full-text search
CREATE INDEX IF NOT EXISTS idx_questions_search_vector
    ON acq.questions USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS idx_answers_search_vector
    ON acq.answers USING GIN (search_vector);
"""


def create_tables(conn) -> None:
    """Execute DDL to create the acq schema and all tables.

    *conn* must be a psycopg2 connection (or compatible). The DDL is issued
    directly on that connection, so its role needs CREATE on the database.
    On managed Postgres offerings whose default role lacks CREATE, the
    connection must already have been elevated to an owning role -- for
    example by a provider-supplied helper such as ``sp_set_role_dbowner()``
    -- before this is called.
    """
    cur = conn.cursor()
    cur.execute(_DDL)

    cur.execute("SELECT version FROM acq.schema_version")
    row = cur.fetchone()
    current_version = row[0] if row else 0

    if current_version == 0:
        cur.execute(
            "INSERT INTO acq.schema_version (version) VALUES (%s)",
            (SCHEMA_VERSION,),
        )
    elif current_version < SCHEMA_VERSION:
        cur.execute("UPDATE acq.schema_version SET version = %s", (SCHEMA_VERSION,))

    # v1→v2: rebuild tsvectors to include tag names.
    if current_version == 1:
        _migrate_v1_to_v2(cur)

    conn.commit()
    cur.close()


def _migrate_v1_to_v2(cur) -> None:
    """Rebuild question tsvectors to include associated tag names."""
    cur.execute("""
        UPDATE acq.questions q SET search_vector = to_tsvector('english',
            (q.data::json->>'title') || ' ' ||
            (q.data::json->>'body') || ' ' ||
            COALESCE(
                (SELECT string_agg(t.name, ' ')
                 FROM acq.tags t
                 JOIN acq.question_tags qt ON t.id = qt.tag_id
                 WHERE qt.question_id = q.id),
                ''
            )
        )
    """)
