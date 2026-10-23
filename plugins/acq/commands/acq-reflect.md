---
name: acq:reflect
description: Review the current session for what belongs in ACQ, and for ACQ threads it showed to be wrong.
---

# /acq:reflect

Review the current session for what belongs in ACQ, the team's Stack Overflow.

1. Go back over any ACQ threads used during the session. Upvote answers the work
   actually validated. Edit an answer the work showed to be wrong or incomplete,
   and delete one that is no longer true, saying why. A quirk in an older
   version of a public tool is still true for that version, so name the version
   rather than deleting it.
2. Look for new candidates. The test is whether it would make a good Stack
   Overflow thread, public for a tool or private for our systems: one specific,
   non-obvious problem someone will hit, with an answer that stays true and
   that they could not read straight off the code or docs. Most sessions have
   none, which is the normal outcome.
3. Search for an existing thread before proposing a new one. Improving that
   thread usually beats starting another.
4. Present each candidate with its title, body, answer, and tags, and ask the
   user which to save or revise.
5. Submit the chosen questions with `ask`, then attach their answers. Use
   `supervised: true`, because the user reviewed that exact content here.
6. Report what was saved, edited, deleted, voted on, or skipped.

Write each answer as a good Stack Overflow answer would read: what is true and
what to do. How this session found it, which ticket it was on, and what was on
this machine are not part of the answer.
