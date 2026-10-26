"""SqliteStore shared across threads, as the team API uses it.

The team API hands one sqlite3 connection to FastAPI's threadpool, so requests
reach the store from several threads at once. Interleaved use of one connection
corrupts cursor state and commits one request's half-finished writes with
another's.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from acq_shared.models import Answer, Comment, Question, Vote
from acq_shared.sqlite_store import SqliteStore


def test_concurrent_requests_neither_fail_nor_lose_writes(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "team.db"), check_same_thread=False)
    store = SqliteStore(conn)

    def request(n: int) -> None:
        q = store.create_question(
            Question(
                title=f"pooling question {n}",
                body="sqlite pooling body",
                created_by="a",
                created_by_type="agent",
                supervised=True,
            ),
            ["sqlite", f"tag-{n % 3}"],
        )
        a = store.create_answer(
            Answer(question_id=q.id, body=f"answer {n}", created_by="a", created_by_type="agent", supervised=True)
        )
        store.create_comment(
            Comment(parent_id=a.id, parent_type="answer", body="comment", created_by="a", created_by_type="agent")
        )
        store.cast_vote(Vote(target_id=a.id, target_type="answer", voter_id=f"v{n}", voter_type="agent", value=1))
        store.edit_answer(a.id, f"edited answer {n}", "a", "agent")
        store.search("pooling")
        store.get_question_thread(q.id)

    rounds = 40
    with ThreadPoolExecutor(max_workers=8) as pool:
        failures = [f.exception() for f in [pool.submit(request, n) for n in range(rounds)] if f.exception()]

    assert not failures, f"{len(failures)} requests failed, e.g. {failures[0]!r}"
    status = store.get_status()
    assert (status["total_questions"], status["total_answers"]) == (rounds, rounds)
    conn.close()


def test_a_failed_write_is_not_published_by_the_next_commit(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "team.db"), check_same_thread=False)
    store = SqliteStore(conn)
    good = Question(title="kept out", body="b", created_by="a", created_by_type="agent", supervised=True)
    # The second record fails validation after the first is already written.
    export = {"questions": [good.model_dump(mode="json"), {"id": "q_broken"}]}

    try:
        store.bulk_upsert(export)
    except Exception:
        pass
    else:
        raise AssertionError("bulk_upsert accepted an invalid record")
    store.create_question(
        Question(title="later", body="b", created_by="a", created_by_type="agent", supervised=True), ["t"]
    )

    assert store.get_question(good.id) is None
    conn.close()
