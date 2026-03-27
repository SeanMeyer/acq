from __future__ import annotations

from acq_shared.models import Answer, Question

DEFAULT_HUMAN_VOTE_WEIGHT = 5


def weighted_vote_score(
    *,
    agent_up: int,
    agent_down: int,
    human_up: int,
    human_down: int,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    return (
        (human_up * human_weight) + agent_up
        - (human_down * human_weight) - agent_down
    )


def _entity_vote_score(
    entity: Question | Answer,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    return weighted_vote_score(
        agent_up=entity.agent_upvotes,
        agent_down=entity.agent_downvotes,
        human_up=entity.human_upvotes,
        human_down=entity.human_downvotes,
        human_weight=human_weight,
    )


def search_content_score(
    question: Question,
    best_answer: Answer | None,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    q_score = _entity_vote_score(question, human_weight)
    a_score = _entity_vote_score(best_answer, human_weight) if best_answer else 0.0
    return 0.3 * q_score + 0.7 * a_score


def text_relevance_score(
    *,
    fts_rank: float,
    tag_jaccard: float,
    language_match: bool = False,
    framework_match: bool = False,
) -> float:
    """Combine FTS rank (normalized 0-1) with tag and context signals."""
    return (
        0.7 * tag_jaccard
        + 0.15 * (1.0 if language_match else 0.0)
        + 0.15 * (1.0 if framework_match else 0.0)
    ) * 0.5 + fts_rank * 0.5


def search_score(
    *,
    text_relevance: float,
    question: Question,
    best_answer: Answer | None,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    return text_relevance * search_content_score(question, best_answer, human_weight)


def rank_answers(
    answers: list[Answer],
    pinned_id: str | None,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> list[Answer]:
    def sort_key(a: Answer) -> tuple[bool, float]:
        is_pinned = a.id == pinned_id
        score = _entity_vote_score(a, human_weight)
        return (is_pinned, score)

    return sorted(answers, key=sort_key, reverse=True)
