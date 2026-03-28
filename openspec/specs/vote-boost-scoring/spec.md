## ADDED Requirements

### Requirement: Isolated vote boost function

The system SHALL provide a `vote_boost(content_score: float) -> float` function in `scoring.py` that computes the vote-based multiplier for search ranking. The function SHALL use `log1p(max(0.0, content_score))` as its default implementation. The function MUST be the single point where vote-to-score translation occurs — no other code path SHALL compute this transformation.

#### Scenario: Zero votes produce no boost
- **WHEN** `vote_boost` is called with `content_score = 0.0`
- **THEN** it SHALL return `0.0` (since `log1p(0) = 0`)

#### Scenario: Small vote count produces meaningful boost
- **WHEN** `vote_boost` is called with `content_score = 2.0`
- **THEN** it SHALL return approximately `1.1` (`log(3) ≈ 1.099`)

#### Scenario: Large vote count produces bounded boost
- **WHEN** `vote_boost` is called with `content_score = 50.0`
- **THEN** it SHALL return approximately `3.93` (`log(51) ≈ 3.932`)

#### Scenario: Negative content score is floored
- **WHEN** `vote_boost` is called with `content_score = -5.0`
- **THEN** it SHALL return `0.0` (floored at zero before log)

### Requirement: Search score uses additive log boost

The `search_score` function SHALL compute `text_relevance * (1.0 + vote_boost(content_score))` where `content_score` comes from the existing `search_content_score` function. This replaces the current `text_relevance * content_score` formula.

#### Scenario: New content with zero votes ranks on text relevance
- **WHEN** a question has 0 votes on both question and best answer
- **AND** the FTS5 text match produces `text_relevance = 0.9`
- **THEN** `search_score` SHALL return `0.9 * (1.0 + 0.0) = 0.9`

#### Scenario: Voted content gets boosted above unvoted content
- **WHEN** question A has `text_relevance = 0.9` and 0 votes (content_score = 0)
- **AND** question B has `text_relevance = 0.9` and content_score = 5.0
- **THEN** question B SHALL rank higher (`0.9 * (1 + 1.79) = 2.51` vs `0.9`)

#### Scenario: Text relevance still matters against moderate votes
- **WHEN** question A has `text_relevance = 0.9` and 0 votes
- **AND** question B has `text_relevance = 0.2` and content_score = 5.0
- **THEN** question B scores `0.2 * 2.79 = 0.56`, question A scores `0.9`
- **AND** question A (better text match, no votes) SHALL rank higher

### Requirement: Content score calculation unchanged

The `search_content_score` function SHALL continue to use the existing formula: `0.3 * question_vote_score + 0.7 * best_answer_vote_score`. The `weighted_vote_score` function SHALL continue to weight human votes at `DEFAULT_HUMAN_VOTE_WEIGHT` (5) times agent votes.

#### Scenario: Human and agent vote weighting preserved
- **WHEN** a question has 1 human upvote and 1 agent upvote
- **THEN** `weighted_vote_score` SHALL return `5 * 1 + 1 = 6`
