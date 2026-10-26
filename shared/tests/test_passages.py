"""Replacing one passage of a body."""

from __future__ import annotations

import pytest
from acq_shared.passages import PassageError, replace_passage


def test_replaces_the_one_place_the_passage_appears() -> None:
    assert replace_passage("Use port 5432.\n\nSet a timeout.", "port 5432", "port 15432") == (
        "Use port 15432.\n\nSet a timeout."
    )


@pytest.mark.parametrize(
    ("body", "old_text", "new_text", "detail"),
    [
        ("port 1", "port 9", "x", "does not appear"),
        ("port 1, port 2", "port", "x", "more than once"),
        # Overlapping occurrences are still two places.
        ("retry, retry, retry", "retry, retry", "x", "more than once"),
        ("port 1", "port 1", "", "leave the text empty"),
        ("port 1", "", "x", "non-empty"),
    ],
)
def test_refuses_anything_but_exactly_one_place(body: str, old_text: str, new_text: str, detail: str) -> None:
    with pytest.raises(PassageError, match=detail):
        replace_passage(body, old_text, new_text)
