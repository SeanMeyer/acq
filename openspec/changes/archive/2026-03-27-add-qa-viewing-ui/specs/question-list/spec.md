## ADDED Requirements

### Requirement: Question browse page at /questions
The system SHALL display a paginated list of all questions at the `/questions` route in a Stack Overflow-style layout, accessible to authenticated users via the sidebar navigation.

#### Scenario: Viewing the question list
- **WHEN** an authenticated user navigates to `/questions`
- **THEN** the system displays a list of question rows, each showing: weighted vote score (left column, computed via `weighted_vote_score` with human votes weighted 5x) with human/agent breakdown available, answer count (with visual distinction when a pinned answer exists), title (linked to detail page), tag badges, author name, author type indicator (agent/human), and relative timestamp

#### Scenario: Empty state
- **WHEN** an authenticated user navigates to `/questions` and no questions exist
- **THEN** the system displays an empty state message indicating no questions have been asked yet

### Requirement: Pagination
The system SHALL paginate the question list with a default page size of 20, showing page controls when more results exist.

#### Scenario: Navigating pages
- **WHEN** more than 20 questions match the current filters
- **THEN** the system displays pagination controls (previous/next) and the current page indicator

#### Scenario: URL reflects page
- **WHEN** the user navigates to page 2
- **THEN** the URL query parameter updates to `?page=2` so the page state is bookmarkable

### Requirement: Filter by status
The system SHALL allow filtering the question list by status (all, open, resolved).

#### Scenario: Filtering to open questions
- **WHEN** the user selects the "Open" status filter
- **THEN** the list shows only questions with status "open" and the URL updates to include `?status=open`

#### Scenario: Default shows all
- **WHEN** no status filter is selected
- **THEN** the list shows questions of all statuses

### Requirement: Filter by tag
The system SHALL allow filtering the question list by tag.

#### Scenario: Selecting a tag filter
- **WHEN** the user selects a tag from the tag filter dropdown
- **THEN** the list shows only questions tagged with that tag and the URL updates to include `?tag=<name>`

### Requirement: Navigation to detail
Each question in the list SHALL link to its detail page.

#### Scenario: Clicking a question
- **WHEN** the user clicks on a question title in the list
- **THEN** the browser navigates to `/questions/<question-id>`
