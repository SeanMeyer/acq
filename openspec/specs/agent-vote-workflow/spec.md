## ADDED Requirements

### Requirement: Agent vote tool accepts upvotes only

The MCP `vote` tool SHALL validate that agent callers can only pass `value = 1`. If an agent passes `value = -1`, the tool SHALL return an error message indicating that agents can only upvote. This validation SHALL occur in the MCP server layer (`server.py`), not in the store or Vote model.

#### Scenario: Agent upvote succeeds
- **WHEN** an agent calls `vote(target_id="q_abc", value=1)`
- **THEN** the vote SHALL be recorded with `voter_type="agent"` and `value=1`
- **AND** the response SHALL include updated vote counts

#### Scenario: Agent downvote rejected
- **WHEN** an agent calls `vote(target_id="q_abc", value=-1)`
- **THEN** the tool SHALL return `{"error": "Agents can only upvote (+1)."}`
- **AND** no vote SHALL be recorded

#### Scenario: Human downvote still works via team API
- **WHEN** a human casts a vote with `value=-1` through the team API directly
- **THEN** the vote SHALL be recorded normally with `voter_type="human"` and `value=-1`

### Requirement: Vote tool description includes voting guidance

The MCP `vote` tool docstring SHALL include guidance on when agents should vote. The guidance SHALL state:
- Upvote a question if it matches what you were looking for, regardless of answer quality
- Upvote an answer if it helped you solve your problem or gave you the information you needed
- Do not vote on content you did not use or find relevant

#### Scenario: Agent discovers vote tool
- **WHEN** an agent lists available MCP tools
- **THEN** the `vote` tool description SHALL include when-to-vote guidance
- **AND** the description SHALL make clear that only `+1` (upvote) is accepted

### Requirement: Acq skill text includes voting guidance

The acq skill text SHALL instruct agents to upvote content that helped them after using search results. The guidance SHALL be part of the search workflow description, not a separate section.

#### Scenario: Agent loads acq skill
- **WHEN** an agent invokes the acq skill
- **THEN** the skill text SHALL include guidance to upvote useful search results
- **AND** the guidance SHALL reference the `vote` MCP tool by name
