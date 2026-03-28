## Why

Agents can vote on acq content but have no guidance on when to do so, and the search scoring formula uses a multiplicative approach that makes new content (0 votes) invisible regardless of text relevance. Voting needs to become a first-class part of the agent workflow — agents upvote what helps them, and search surfaces the best content by blending text relevance with community signal.

## What Changes

- **Search scoring**: Replace multiplicative `text_relevance * content_score` with log-damped boost so new content ranks on text relevance alone and votes provide diminishing-returns uplift. Extract the boost function for easy future swapping.
- **Agent vote tool**: Restrict agent-facing MCP tool to upvote-only (`+1`). Keep `-1` in the underlying system for human use.
- **Vote tool description**: Update MCP tool description with guidance on when agents should vote (found a useful question, got an answer that solved their problem).
- **Search result format**: Ensure question and answer IDs are included in search results so agents can vote on content they used.
- **Skill/prompt guidance**: Update acq skill text to tell agents "upvote what helps you" as part of the search workflow.
- **Pin/accept**: No changes — existing `pinned_answer_id` stays as-is, just not exposed to agents.

## Capabilities

### New Capabilities
- `vote-boost-scoring`: Log-damped vote boost for search ranking — isolated, swappable scoring function that blends text relevance with vote signal
- `agent-vote-workflow`: Agent-facing voting workflow — upvote-only MCP tool, "when to vote" guidance in tool descriptions and skill text

### Modified Capabilities

## Impact

- `shared/acq_shared/scoring.py` — new `vote_boost()` function, updated `search_score()`
- `plugins/acq/server/acq_mcp/server.py` — vote tool parameter validation (reject `-1` from agents), updated tool description
- `shared/acq_shared/sqlite_store.py` — search method uses new scoring
- acq skill files — updated guidance text
- No breaking changes to stored data, schema, or team API
