## ADDED Requirements

### Requirement: Search page at /search
The system SHALL provide a dedicated search page at `/search` for full-text searching the knowledge base, separate from the browse list.

#### Scenario: Searching by keyword
- **WHEN** an authenticated user enters a search query on the `/search` page and submits
- **THEN** the system displays results ranked by relevance, showing question title, body excerpt/snippet, tags, answer count, and vote score

#### Scenario: Empty search state
- **WHEN** the user navigates to `/search` without a query
- **THEN** the system displays a search input with placeholder text and no results

#### Scenario: No results
- **WHEN** the user searches for a term with no matching questions
- **THEN** the system displays a "No results found" message with the search term echoed back

#### Scenario: URL reflects query
- **WHEN** the user submits a search for "deployment"
- **THEN** the URL updates to `/search?q=deployment` so the search is bookmarkable/shareable

### Requirement: Search results link to detail
Each search result SHALL link to the question detail page.

#### Scenario: Clicking a search result
- **WHEN** the user clicks on a search result title
- **THEN** the browser navigates to `/questions/<question-id>`

### Requirement: Search from anywhere
The system SHALL provide a way to initiate a search from any page (e.g., a search input in the nav/header area).

#### Scenario: Using the global search input
- **WHEN** the user types a query into the global search input and submits
- **THEN** the browser navigates to `/search?q=<query>` with the results displayed
