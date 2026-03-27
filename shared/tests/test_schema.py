import sqlite3
from acq_shared.sqlite_schema import create_tables, SCHEMA_VERSION


class TestSchema:
    def test_creates_all_tables(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "questions", "answers", "comments", "votes",
            "edit_history", "tags", "question_tags",
            "schema_version",
        }
        assert expected.issubset(tables)

    def test_fts5_index_created(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "search_index" in tables

    def test_schema_version_recorded(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        version = conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        create_tables(conn)
        create_tables(conn)  # should not error
