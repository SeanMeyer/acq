## 1. Store Layer

- [x] 1.1 Add `list_questions(status, tag, offset, limit) -> tuple[list[dict], int]` to the `Store` protocol in `shared/acq_shared/store.py` (each dict contains question + its tags)
- [x] 1.2 Implement `list_questions` in `SqliteStore` (`shared/acq_shared/sqlite_store.py`) — query with optional WHERE clauses for status and tag (via question_tags join), ORDER BY created_at DESC, with LIMIT/OFFSET and a COUNT query for total; include tags per question
- [x] 1.3 Implement `list_questions` in `PostgresStore` (`shared/acq_shared/postgres_store.py`) — same logic using Postgres SQL
- [x] 1.4 Verify `get_question_thread` returns pending answers (not just approved) — update if needed so the detail page can show them
- [x] 1.5 Add contract tests for `list_questions` in `shared/tests/test_store_contract.py` — cover: no filters, status filter, tag filter, pagination with total count, empty results

## 2. API Endpoints

- [x] 2.1 Create `team-api/team_api/questions.py` router with `GET /questions` endpoint (JWT auth via `get_current_user`): accepts `status`, `tag`, `limit`, `offset` query params; delegates to `store.list_questions`; returns `{items, total}`
- [x] 2.2 Add `GET /search` endpoint to the questions router (JWT auth): accepts required `q` param plus optional `tags`, `language`, `framework`, `limit`; delegates to `store.search()`; returns 400 if `q` is missing
- [x] 2.3 Add `GET /questions/{question_id}/thread` endpoint: returns full thread via `store.get_question_thread()`, 404 if not found; response includes pending answers; sort answers using `rank_answers()` from `scoring.py`
- [x] 2.4 Register the questions router in `team-api/team_api/app.py` via `app.include_router()`
- [x] 2.5 Add tests for all endpoints in `team-api/tests/test_questions.py` — cover: list with filters, pagination, search with/without query, thread fetch with answer sort order, 404, auth required

## 3. Frontend Scoring Utility

- [x] 3.1 Create `team-ui/src/lib/scoring.ts` — port `weighted_vote_score` formula: `(human_up * 5) + agent_up - (human_down * 5) - agent_down`; export a function that takes a `VoteCounts` object and returns the weighted score

## 4. Frontend API Client

- [x] 4.1 Add TypeScript types to `team-ui/src/lib/types.ts`: `QuestionListResponse` (items with tags + total), `QuestionThread` (question + answers with comments, including pending answers)
- [x] 4.2 Add API methods to `team-ui/src/lib/api.ts`: `listQuestions(params)`, `searchQuestions(q)`, and `questionThread(id)`

## 5. Question List Page (Browse)

- [x] 5.1 Create `team-ui/src/routes/questions/+page.svelte` — Stack Overflow-style paginated list with status filter tabs (All/Open/Resolved), tag filter dropdown, and question rows linking to detail pages; URL query params for filters and page
- [x] 5.2 Create `team-ui/src/components/QuestionRow.svelte` — SO-style row: weighted vote score (left, single number with human/agent breakdown available), answer count (with accent if pinned answer exists), title link, tag badges, author + type indicator + relative timestamp

## 6. Search Page

- [x] 6.1 Create `team-ui/src/routes/search/+page.svelte` — dedicated search page with search input, relevance-ranked results showing title, body excerpt, tags, answer count; URL query param `?q=`
- [x] 6.2 Add global search input to the layout header/nav that navigates to `/search?q=<query>` on submit

## 7. Question Detail Page

- [x] 7.1 Create `team-ui/src/routes/questions/[id]/+page.svelte` — full thread view: question body (markdown), metadata (tags, context, author type), weighted vote score with breakdown; approved answers section sorted by `rank_answers()`; pending answers section (muted); back link to `/questions`
- [x] 7.2 Create `team-ui/src/components/AnswerCard.svelte` — answer display: markdown body, weighted vote score with human/agent breakdown, author + type indicator + timestamp, pinned indicator (for pinned answer), nested comments; when `status === "pending"`: muted/grayed styling + inline approve/reject buttons using existing `api.approve()`/`api.reject()`

## 8. Navigation

- [x] 8.1 Update `team-ui/src/routes/+layout.svelte` to add "Questions" link in the sidebar navigation
