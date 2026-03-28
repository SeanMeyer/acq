## Context

The Accrue team-ui is a Svelte 5 + SvelteKit app with two existing routes: `/review` (Tinder-style approval queue for pending content) and `/dashboard` (aggregate stats, tag management). The backend (`team-api`) is a FastAPI service backed by the `Store` protocol with SQLite and Postgres implementations.

The store already supports `get_question_thread(id)` (returns full thread with answers and comments) and `search(query, tags, language, framework, limit)` (full-text search returning threads). However, there is no `list_questions` method for paginated browsing without a search query, and no human-facing API endpoints for either listing or viewing questions.

The existing UI components (`ReviewCard`, `Markdown`, `VoteBadge`, `StatusBadge`, `TagManager`) provide a design language and reusable pieces to build on.

**Voting model:** The store tracks four vote counts per question/answer: `agent_upvotes`, `agent_downvotes`, `human_upvotes`, `human_downvotes`. A `scoring.py` module already provides `weighted_vote_score` (1 human vote = 5 agent votes) and `rank_answers` (pinned first, then by weighted score). Agent voting is currently opt-in (explicit `vote` tool). A future "I used this" signal (distinct from "I found this") will drive more meaningful vote data — but is out of scope here.

## Goals / Non-Goals

**Goals:**
- Stack Overflow-style browsing and reading experience for the knowledge base
- Interactive thread view — approve/reject pending answers inline, not just from the review queue
- Separate browse and search experiences (different mental models: "what's here?" vs. "find something specific")
- Use existing weighted vote scoring (human 5x agent) for sort order and display

**Non-Goals:**
- Permissions system (for now, any authenticated user can take any action)
- Creating new questions or answers from the UI (agents do this via MCP)
- "I used this answer" usage signal for agents (follow-up — needs its own design for what constitutes "usage" vs. "found in search")
- Real-time updates / WebSocket subscriptions
- Mobile-specific layout (existing responsive Tailwind approach is sufficient)

## Decisions

### 1. Separate browse and search pages

`/questions` is the browse page — paginated list, filter by status/tag, sorted by recency. `/search` is the search page — full-text query, results ranked by relevance.

**Why:** These are different user intents with different result shapes. Browse answers "what's in the knowledge base?" (recency-sorted, filterable). Search answers "where's that thing about X?" (relevance-ranked). Combining them into one page creates UX confusion when switching between modes changes sort order and result format.

**Alternative considered:** Single page with search bar that toggles modes. Rejected because the result rendering differs (search shows relevance snippets/highlights, browse shows stats-focused rows).

### 2. Interactive detail page with inline review actions

The question detail page at `/questions/[id]` is not read-only. Pending answers are shown at the bottom in a muted/grayed-out style, with approve/reject buttons. This lets reviewers handle pending content in context rather than through the separate review queue.

**Why:** When you're looking at a question and see a pending answer, you have the full context to decide. Forcing the reviewer to find that same item in the review queue is unnecessary friction. Stack Overflow works the same way — moderator actions are inline.

**Permissions note:** For now, any authenticated user can approve/reject. Permissions are a future concern.

### 3. Weighted vote scoring for sort order and display

Use the existing `weighted_vote_score` from `scoring.py`: `score = (human_up * 5) + agent_up - (human_down * 5) - agent_down`. This applies to both questions (list page sort) and answers (detail page sort).

Within the detail page:
1. Pinned answer (if any) — visually distinguished
2. Approved answers — sorted by weighted vote score desc, then `created_at` asc as tiebreaker
3. Pending answers — grayed out at bottom, sorted chronologically

The existing `rank_answers()` function already implements pinned-first + weighted score sorting — reuse it directly.

**Vote display:** Show a single weighted score number as the primary signal. The human/agent vote breakdown is available via a clean secondary treatment (exact UX to be refined during implementation — could be subtle inline text, an expandable detail, or similar). The goal is: scannable at a glance, detailed on demand.

**Why:** Human curation is more valuable than agent voting (humans verify correctness; agents signal frequency of use). The 5x weight reflects this. A single number is scannable; showing four raw counts would be noise. The breakdown lets curious users understand the composition without cluttering the default view.

**Alternative considered:** Raw net vote count ignoring voter type. Rejected because it doesn't reflect the trust asymmetry between human and agent votes.

### 4. Stack Overflow-style question rows

Each question in the list shows a compact row with:
- Weighted vote score (left, numerical) with human/agent breakdown available
- Answer count (with visual distinction for "has accepted/pinned answer")
- Title (links to detail)
- Tags (inline badges)
- Author + relative timestamp (right-aligned)

**Why:** This layout is proven and familiar. It frontloads the two signals users scan for: "how popular is this?" and "is it answered?"

### 5. Route structure

- `/questions` — browse list
- `/questions/[id]` — detail/thread
- `/search` — dedicated search

SvelteKit file-based routing: `src/routes/questions/+page.svelte`, `src/routes/questions/[id]/+page.svelte`, `src/routes/search/+page.svelte`.

### 6. Reuse existing API patterns and components

- `Markdown.svelte` for rendering question/answer bodies
- `VoteBadge.svelte` for vote counts
- `StatusBadge.svelte` for open/resolved/pending badges
- `ReviewActions.svelte` for inline approve/reject on pending answers
- Same JWT auth (`get_current_user`) as existing review routes
- Existing Tailwind design tokens

New components: `QuestionRow.svelte` (list item), `AnswerCard.svelte` (detail page answer block with optional review actions).

## Risks / Trade-offs

- **[Sparse votes initially] Most answers will show score 0** → Agent voting is opt-in and there's no "usage" signal yet. Mitigated by chronological tiebreaker so sort order is still deterministic. The weighted score system is ready to be useful once a future "I used this" feature drives more vote data.
- **[Store protocol change] Adding `list_questions` requires updating both store implementations** → Method is straightforward (SELECT with optional WHERE clauses). Contract tests ensure parity.
- **[Inline review actions blur the review workflow]** → A reviewer might approve an answer from the detail page and then see it again in the review queue (or vice versa). Mitigated by optimistic removal: when approved/rejected from either location, it's removed from the pending queue. The review queue already handles this via `approve_content`/`reject_content` store methods.
- **[No permissions yet]** → Any authenticated user can approve/reject. Acceptable for now since the user pool is small (team members). Flag for future work.
