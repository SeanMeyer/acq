from __future__ import annotations

import math
import re

from acq_shared.models import Answer, Question

DEFAULT_HUMAN_VOTE_WEIGHT = 5

# Minimum duplicate_similarity() for a stored question to be shown to the
# caller as a possible duplicate.
#
# Tuned for recall, because the consumer is an agent that can judge for itself.
# A candidate that turns out to be irrelevant costs the agent one extra call
# (retry with force_create); a candidate never returned is invisible, and the
# agent silently files a duplicate having never learned the earlier question
# existed. Those costs are not symmetric, so err towards showing.
#
# Calibrated against a corpus of realistic title pairs: genuine duplicates
# scored no lower than 0.40 and unrelated pairs no higher than 0.30, so this
# sits in the middle of that gap rather than on either edge.
DUPLICATE_THRESHOLD = 0.35

# Word characters minus the underscore, so this covers CJK, Cyrillic, accented
# Latin and so on. An ASCII-only pattern such as `[a-z0-9]+` would tokenise a
# non-Latin title to nothing, and two identical such titles would then score
# 0.0 similarity and never be recognised as duplicates.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Question titles are mostly phrased as questions, so the same handful of
# function words appears in nearly all of them. Left in, they inflate both the
# intersection (unrelated titles "match" on "how"/"do"/"the") and the union
# (real duplicates are diluted). Removing them sharpens both directions at
# once. This is not a linguistic stopword list, just the filler that shows up
# in how questions get worded.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "i",
        "my",
        "me",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "and",
        "or",
        "but",
        "not",
        "no",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "from",
        "with",
        "without",
        "by",
        "about",
        "into",
        "over",
        "after",
        "before",
        "how",
        "what",
        "why",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "if",
        "then",
        "than",
        "as",
        "so",
        "such",
        "very",
        "just",
        "only",
        "also",
    ]
)


def _tokenize(text: str) -> set[str]:
    """Content words of *text*, lowercased.

    Falls back to the unfiltered tokens when a title consists entirely of
    filler ("How do I do this?"), so such a title still compares equal to
    itself rather than collapsing to an empty set.
    """
    tokens = set(_TOKEN_RE.findall(text.casefold()))
    content = tokens - _STOPWORDS
    return content or tokens


def jaccard(a: set[str], b: set[str]) -> float:
    """Intersection over union. 0.0 when both sides are empty."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def duplicate_similarity(
    *,
    query_title: str,
    candidate_title: str,
    query_tags: set[str],
    candidate_tags: set[str],
) -> float:
    """Absolute 0-1 similarity between two questions, for duplicate detection.

    Deliberately independent of the full-text engine. Search rank is a
    *relative* measure — it is min-max scaled across whatever the query
    happened to match, so a single weak match normalises to the maximum and
    looks identical to a perfect one. Judging "is this the same question"
    needs an absolute measure, so this compares the titles directly.

    Because both store backends call this, Postgres and SQLite necessarily
    agree instead of drifting apart.

    Title agreement dominates; shared tags are a smaller bonus. Jaccard
    (rather than an overlap/containment ratio) is used on purpose: containment
    would score a one-word query against a long title as a perfect match, so
    every short question would look like a duplicate of the longest stored one.

    This measure is meant to *rank and admit candidates*, not to deliver a
    verdict. The caller is an agent that receives the candidates along with
    their scores and decides whether any of them really asks its question, so
    the threshold is deliberately permissive — see DUPLICATE_THRESHOLD.

    Known limitations. There is no stemming, synonym expansion, or stopword
    removal, so "widget" and "widgets" share no token and filler words inflate
    the union. The effect is that heavily reworded duplicates score lower than
    they deserve, which is why the threshold sits well below the level an
    exact-title match reaches.
    """
    title_sim = jaccard(_tokenize(query_title), _tokenize(candidate_title))
    tag_sim = jaccard(query_tags, candidate_tags)
    return 0.7 * title_sim + 0.3 * tag_sim


def weighted_vote_score(
    *,
    agent_up: int,
    agent_down: int,
    human_up: int,
    human_down: int,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    return (human_up * human_weight) + agent_up - (human_down * human_weight) - agent_down


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
    """Combine FTS rank (normalized 0-1) with optional context signals.

    Tags are now indexed in FTS, so the FTS rank already reflects tag
    relevance.  The context signals (explicit tag Jaccard, language,
    framework) act as a *bonus* on top — they never diminish the FTS
    score.
    """
    context_bonus = (
        0.7 * tag_jaccard + 0.15 * (1.0 if language_match else 0.0) + 0.15 * (1.0 if framework_match else 0.0)
    )
    return fts_rank + 0.3 * context_bonus


def vote_boost(content_score: float) -> float:
    """Log-damped boost from vote-based content score.

    Returns 0 for unvoted content (no penalty), with diminishing returns
    as votes accumulate.  Swap this function to change the vote-to-ranking
    algorithm without touching the rest of the scoring pipeline.
    """
    return math.log1p(max(0.0, content_score))


def search_score(
    *,
    text_relevance: float,
    question: Question,
    best_answer: Answer | None,
    human_weight: int = DEFAULT_HUMAN_VOTE_WEIGHT,
) -> float:
    content = search_content_score(question, best_answer, human_weight)
    return text_relevance * (1.0 + vote_boost(content))


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
