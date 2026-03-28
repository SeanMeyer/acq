## ADDED Requirements

### Requirement: List questions endpoint
The system SHALL expose `GET /questions` as a human-facing, JWT-authenticated endpoint that returns a paginated list of questions with optional filters.

#### Scenario: Listing all questions
- **WHEN** a request is made to `GET /questions`
- **THEN** the system returns a JSON response with `items` (list of question objects, each including its tags) and `total` (total count matching filters), defaulting to 20 items at offset 0, ordered by `created_at` descending

#### Scenario: Filtering by status
- **WHEN** a request includes `?status=open`
- **THEN** the system returns only questions with status "open"

#### Scenario: Filtering by tag
- **WHEN** a request includes `?tag=python`
- **THEN** the system returns only questions tagged with "python"

#### Scenario: Pagination
- **WHEN** a request includes `?limit=10&offset=20`
- **THEN** the system returns at most 10 questions starting from offset 20, and `total` reflects the full count matching filters

#### Scenario: Unauthorized access
- **WHEN** a request is made without a valid JWT
- **THEN** the system returns HTTP 401

### Requirement: Search questions endpoint
The system SHALL expose `GET /search` as a human-facing, JWT-authenticated endpoint that returns relevance-ranked search results.

#### Scenario: Searching by keyword
- **WHEN** a request is made to `GET /search?q=deployment`
- **THEN** the system delegates to the store's `search()` method and returns matching question threads ranked by relevance

#### Scenario: Empty query
- **WHEN** a request is made to `GET /search` without a `q` parameter
- **THEN** the system returns HTTP 400 with detail "Search query required"

#### Scenario: Unauthorized access
- **WHEN** a request is made without a valid JWT
- **THEN** the system returns HTTP 401

### Requirement: Question thread endpoint
The system SHALL expose `GET /questions/{id}/thread` as a human-facing, JWT-authenticated endpoint that returns the full question thread including pending answers.

#### Scenario: Fetching an existing thread
- **WHEN** a request is made to `GET /questions/<id>/thread` for an existing question
- **THEN** the system returns the question object with its tags, all answers (approved and pending, with their comments), and all question-level comments

#### Scenario: Thread includes pending answers
- **WHEN** a question has pending answers
- **THEN** the thread response includes those answers with `status: "pending"` so the UI can render them distinctly

#### Scenario: Question not found
- **WHEN** a request is made to `GET /questions/<id>/thread` for a non-existent question
- **THEN** the system returns HTTP 404 with detail "Question not found"

#### Scenario: Unauthorized access
- **WHEN** a request is made without a valid JWT
- **THEN** the system returns HTTP 401

### Requirement: Store list_questions method
The system SHALL add a `list_questions(status, tag, offset, limit)` method to the `Store` protocol, returning a tuple of `(questions_with_tags, total_count)`.

#### Scenario: Listing without filters
- **WHEN** `list_questions` is called with no status or tag filter
- **THEN** the method returns all questions ordered by `created_at` descending, with each question including its associated tags

#### Scenario: Filtering by status
- **WHEN** `list_questions` is called with `status="open"`
- **THEN** the method returns only questions with status "open"

#### Scenario: Filtering by tag
- **WHEN** `list_questions` is called with `tag="go"`
- **THEN** the method returns only questions that have the tag "go"

#### Scenario: Pagination
- **WHEN** `list_questions` is called with `offset=10, limit=5`
- **THEN** the method returns at most 5 questions starting from the 11th result, and `total_count` reflects the full count matching the filters (not just the page)

#### Scenario: Both SqliteStore and PostgresStore implement list_questions
- **WHEN** the method is called on either store implementation
- **THEN** the results are identical for the same dataset (verified by shared contract tests)
