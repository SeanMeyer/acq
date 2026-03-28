## 1. Scoring Formula

- [x] 1.1 Add `vote_boost(content_score: float) -> float` function to `shared/acq_shared/scoring.py` using `math.log1p(max(0.0, content_score))`
- [x] 1.2 Update `search_score()` to use `text_relevance * (1.0 + vote_boost(content_score))` instead of `text_relevance * content_score`
- [x] 1.3 Add unit tests for `vote_boost` covering zero, small, large, and negative inputs
- [x] 1.4 Add unit tests for `search_score` verifying new content (0 votes) gets nonzero score, and voted content ranks above unvoted with equal text relevance
- [x] 1.5 Update scoring tests in `shared/tests/` if any existing tests assert the old multiplicative behavior

## 2. Agent Vote Restriction

- [x] 2.1 Add `value == 1` validation in the MCP server vote handler (`plugins/acq/server/acq_mcp/server.py`) that returns an error for `-1`
- [x] 2.2 Add test for agent downvote rejection at MCP layer
- [x] 2.3 Verify human downvotes via team API are unaffected (existing test coverage or new test)

## 3. Vote Tool Description

- [x] 3.1 Update the MCP `vote` tool docstring with when-to-vote guidance and upvote-only restriction
- [x] 3.2 Update the acq skill text to include "upvote what helps you" as part of the search workflow

## 4. Integration Verification

- [x] 4.1 Run `search()` end-to-end test: insert Q&A with 0 votes, verify it returns with nonzero score
- [x] 4.2 Run `search()` end-to-end test: insert two Q&A pairs with same text relevance but different vote counts, verify voted one ranks higher
