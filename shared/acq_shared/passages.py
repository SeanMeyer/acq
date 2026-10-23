"""Replacing one passage of a body, the way an agent edits part of a file.

Agents keep answers current by changing the part that went stale. Sending the
whole body back is expensive for a long answer and, when the agent read it from
a local copy that syncs hourly, can overwrite a newer edit made on the team.
Matching a passage against the current text avoids both.
"""

from __future__ import annotations


class PassageError(ValueError):
    """The passage to replace is not exactly one place in the current text."""


def replace_passage(body: str, old_text: str, new_text: str) -> str:
    if not old_text:
        raise PassageError("old_text must be non-empty.")
    count = body.count(old_text)
    if count == 0:
        raise PassageError("old_text does not appear in the current text. Read the thread again and copy it exactly.")
    if count > 1:
        raise PassageError(f"old_text appears {count} times. Include more surrounding text so it matches once.")
    result = body.replace(old_text, new_text, 1)
    if not result.strip():
        raise PassageError("That would leave the text empty. To remove it, use delete.")
    return result
