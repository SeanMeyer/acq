---
name: acq:status
description: Display acq knowledge store statistics — question/answer counts, tags, vote totals, and team API connectivity.
---

# /acq:status

Display a summary of the acq knowledge store.

## Instructions

1. Call the `status` MCP tool (no arguments needed).
2. Format the response as a readable summary using the sections below.

## Output Format

Present the results using this structure:

```
## acq Knowledge Store

**{total_questions} questions · {total_answers} answers**
Unanswered: {unanswered_count} · Pending review: {pending_count}
Pending questions: {pending_questions_count}

### Tags
{tag}: {count} | {tag}: {count} | ...

### Vote Totals
Agent: {agent_upvotes}↑ {agent_downvotes}↓ · Human: {human_upvotes}↑ {human_downvotes}↓

### Team API
{team_status}
```

## Counts

`total_questions` and `unanswered` count live questions only. Questions awaiting review are reported separately as `pending_questions`. The `pending` field counts answers and comments awaiting review.

## Empty Store

When total_questions is 0:

- Display only: "The acq store is empty. Questions are added when agents call `ask`, or via the `/acq:reflect` command."

## Team API Status

- If `team_status` is "reachable": show "Connected to team API"
- If `team_status` is "unreachable": show "Team API unreachable — running in local-only mode"
