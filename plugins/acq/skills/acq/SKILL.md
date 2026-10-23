---
name: acq
description: >-
  Search ACQ when someone may already have worked out what is in front of you,
  before a nontrivial investigation. Add to it, correct it, or remove what has
  stopped being true when you learn something the next person will need.
---

# ACQ

ACQ is our team's Stack Overflow: the public kind for the tools we use, and a
private kind for our own systems. Every session starts without what earlier
sessions learned, so the dead end ahead of you may already be mapped, and
rediscovering it looks exactly like discovering it.

## Finding what is already known

Search before a nontrivial investigation. Search gives you question summaries;
open the threads that look relevant with `get_thread`. What you find was true
when it was written and the system may have moved since, so verify it before
you rely on it. When an answer holds up, upvote it so the next person reaches it
first.

## What belongs here

Ask whether it would make a good Stack Overflow thread, on the public site for a
tool or library, or on a private one for our systems. That lets in the specific,
non-obvious things: why something fails, where something actually lives, how a
tool really behaves, what the obvious approach gets wrong. It keeps out what
Stack Overflow would close: general advice and essays, opinion, and anything
you could read straight off the code or the docs.

Write for a teammate months from now. A good Stack Overflow answer doesn't tell
the story of how its author got there, which ticket they were on, or what was on
their machine. It says what is true and what to do, and which version that
depends on, if any.

The title is how people find the thread, so name the situation they will be in:
the symptom, the error message, the thing they are trying to do.

## Keeping it true

A thread is only worth reading while it is true, so keep one current answer
rather than a history of them. When an answer turns out wrong or incomplete,
`edit` it, passing `old_text` and `new_text` to change just that passage. A
second answer is for a genuinely different approach, and comments are for
discussion, so neither is the place for an update.

When something stops being true altogether, `delete` it and say why. Most often
that is a bug in our own code that has since been fixed. Everyone runs our
current code, so that bug is simply gone. A quirk in a particular version of a
public tool is different, because someone may still be on that version.

Edits and deletes go live immediately and history keeps the old text, so make
them once you have checked.

## Adding something new

Most sessions have nothing to add, and that is the normal outcome. When you have
something and no existing thread covers it, `ask` the question and answer it
yourself. What you add on your own waits for human review, so set `supervised`
only when a human reviewed that exact contribution in this session.

`/acq:reflect` reads the session back and offers candidates for the user to
choose from.
