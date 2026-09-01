import sqlite3

from acq_shared.sqlite_schema import SCHEMA_VERSION, create_tables


class TestSchema:
    def test_creates_all_tables(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        expected = {
            "questions",
            "answers",
            "comments",
            "votes",
            "edit_history",
            "tags",
            "question_tags",
            "schema_version",
        }
        assert expected.issubset(tables)

    def test_fts5_index_created(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "search_index" in tables

    def test_schema_version_recorded(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        create_tables(conn)  # should not error

    def test_v3_migration_adds_comment_updated_at(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (3);
            CREATE TABLE comments (
                id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                parent_type TEXT NOT NULL,
                data TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO comments VALUES (
                'c_1', 'q_1', 'question', '{}', 'approved',
                '2026-01-01T00:00:00+00:00'
            );
        """)

        create_tables(conn)

        updated_at = conn.execute("SELECT updated_at FROM comments WHERE id = 'c_1'").fetchone()[0]
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert updated_at == "2026-01-01T00:00:00+00:00"
        assert version == SCHEMA_VERSION
