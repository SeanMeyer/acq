## Why

The team-ui currently has a review queue (approve/reject pending items) and a dashboard (aggregate stats), but no way to **browse the actual knowledge base**. Reviewers and humans can't view resolved questions, read approved answers, search by keyword/tag, or see a full Q&A thread. This means the only way to inspect knowledge is through the MCP plugin's agent-facing tools or raw API calls. Adding a Q&A browsing UI makes the knowledge base accessible to humans for reference, quality auditing, and understanding what agents are learning.

## What Changes

- **New question list page** (`/questions`): paginated, filterable list of all questions in a Stack Overflow-style layout — title, status, tags, answer count, vote score, author
- **New search page** (`/search`): dedicated full-text search experience, separate from the browse list
- **New question detail page** (`/questions/[id]`): interactive Stack Overflow-style thread view — approved answers sorted by votes (pinned first), pending answers shown grayed out at bottom with inline approve/reject actions, comments, vote counts, metadata
- **New API endpoints**: human-facing routes for listing questions (with filtering/pagination), searching, and fetching a full question thread — backed by existing store methods (`search`, `get_question_thread`) plus a new `list_questions` store method
- **Navigation update**: add "Questions" and "Search" links to the sidebar/layout
- **New store method**: `list_questions(status, tag, offset, limit)` for paginated listing without requiring a search query

**Voting & sorting:** The existing `scoring.py` already provides `weighted_vote_score` where 1 human vote = 5 agent votes. The UI uses this weighted score for sorting and displays a single score number with a clean breakdown of human vs agent votes. Agent voting is currently opt-in (explicit `vote` tool call). A deliberate "I used this answer" signal (distinct from "I found this in search results") is a follow-up feature to generate more meaningful vote data.

## Capabilities

### New Capabilities
- `question-list`: Paginated question browsing page with filtering by status (open/resolved) and tag; Stack Overflow-style row layout with title, stats, tags
- `question-search`: Dedicated search page with full-text search, results ranked by relevance
- `question-detail`: Interactive Stack Overflow-style thread view — approved answers sorted by votes (pinned first), pending answers grayed out at bottom with inline approve/reject, comments, vote counts, metadata
- `questions-api`: Human-facing API endpoints for listing questions, searching, and fetching complete question threads

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

- **Frontend** (`team-ui/`): new route files under `src/routes/questions/` and `src/routes/search/`, new components, updated layout nav
- **Backend** (`team-api/`): new `questions.py` router module with endpoints for list, search, and thread; included in `app.py`
- **Shared** (`shared/`): new `list_questions` method added to `Store` protocol and both `SqliteStore`/`PostgresStore` implementations
- **Tests**: new backend tests for question listing/search/thread endpoints, store contract tests for `list_questions`
