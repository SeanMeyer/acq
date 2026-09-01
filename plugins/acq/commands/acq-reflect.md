---
name: acq:reflect
description: Review the current session for hard-won knowledge worth sharing in ACQ.
---

# /acq:reflect

Review the current session for knowledge worth carrying into future work.

1. Review any ACQ answers used during the session. Upvote answers that the work
   actually validated. Add a comment or corrected answer when the work showed
   that an existing answer was incomplete or wrong.
2. Summarize the investigation and call `reflect` with that summary. Continue
   with your own judgment if the tool has no candidates or is unavailable.
3. Identify useful new Q&A candidates. Save knowledge that was genuinely hard
   to obtain and is likely to save substantial future investigation or prevent
   a costly mistake. Prefer information that cannot be recovered quickly from
   code or primary documentation. Skip readable-code summaries and facts whose
   value ends with the current task. Most sessions will have no candidates.
4. Search for duplicates before proposing a new question.
5. Present each candidate with its title, body, answer, and tags. Ask the user
   which candidates to save or revise.
6. Submit selected new questions with `ask`, then attach their answers. Use
   `supervised: true` because the user reviewed the exact content in this flow.
   Add corrected answers to existing questions directly.
7. Report what was saved, skipped, voted on, or corrected.

A question should describe the situation a future agent would recognize. The
answer should contain the useful conclusion, evidence, and changed action rather
than an inventory of source files.
