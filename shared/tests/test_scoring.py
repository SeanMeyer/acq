import math

from acq_shared.models import Answer, Question
from acq_shared.scoring import (
    rank_answers,
    search_content_score,
    search_score,
    text_relevance_score,
    vote_boost,
    weighted_vote_score,
)


class TestWeightedVoteScore:
    def test_agent_only(self):
        score = weighted_vote_score(agent_up=10, agent_down=2, human_up=0, human_down=0)
        assert score == 8  # 10 - 2

    def test_human_weighted(self):
        score = weighted_vote_score(agent_up=0, agent_down=0, human_up=2, human_down=0)
        assert score == 10  # 2 * 5

    def test_mixed(self):
        score = weighted_vote_score(agent_up=10, agent_down=2, human_up=1, human_down=1)
        assert score == 8  # (10-2) + (1*5 - 1*5)

    def test_custom_weight(self):
        score = weighted_vote_score(
            agent_up=0,
            agent_down=0,
            human_up=1,
            human_down=0,
            human_weight=10,
        )
        assert score == 10


class TestSearchContentScore:
    def test_question_only_no_answers(self):
        q = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
            agent_upvotes=10,
            agent_downvotes=0,
        )
        score = search_content_score(q, best_answer=None)
        assert score == 0.3 * 10  # 0.3 * question_score, 0.7 * 0

    def test_with_best_answer(self):
        q = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
            agent_upvotes=10,
            agent_downvotes=0,
        )
        a = Answer(
            question_id=q.id,
            body="Fix",
            created_by="x",
            created_by_type="agent",
            status="approved",
            agent_upvotes=20,
            agent_downvotes=0,
        )
        score = search_content_score(q, best_answer=a)
        assert score == 0.3 * 10 + 0.7 * 20


class TestRankAnswers:
    def test_pinned_first(self):
        a1 = Answer(
            question_id="q_1",
            body="A",
            created_by="x",
            created_by_type="agent",
            status="approved",
            agent_upvotes=100,
        )
        a2 = Answer(
            question_id="q_1",
            body="B",
            created_by="x",
            created_by_type="agent",
            status="approved",
            agent_upvotes=1,
        )
        ranked = rank_answers([a1, a2], pinned_id=a2.id)
        assert ranked[0].id == a2.id  # pinned wins despite fewer votes

    def test_vote_order(self):
        a1 = Answer(
            question_id="q_1",
            body="A",
            created_by="x",
            created_by_type="agent",
            status="approved",
            agent_upvotes=5,
        )
        a2 = Answer(
            question_id="q_1",
            body="B",
            created_by="x",
            created_by_type="agent",
            status="approved",
            agent_upvotes=10,
        )
        ranked = rank_answers([a1, a2], pinned_id=None)
        assert ranked[0].id == a2.id


class TestVoteBoost:
    def test_zero_content_score(self):
        assert vote_boost(0.0) == 0.0

    def test_small_content_score(self):
        result = vote_boost(2.0)
        assert result == math.log1p(2.0)
        assert 1.0 < result < 1.2

    def test_large_content_score(self):
        result = vote_boost(50.0)
        assert result == math.log1p(50.0)
        assert 3.9 < result < 4.0

    def test_negative_content_score_floored(self):
        assert vote_boost(-5.0) == 0.0

    def test_diminishing_returns(self):
        # Equal absolute increments yield smaller boost gains
        first_jump = vote_boost(10.0) - vote_boost(0.0)
        second_jump = vote_boost(20.0) - vote_boost(10.0)
        assert first_jump > second_jump


class TestSearchScore:
    def test_combines_relevance_and_boost(self):
        q = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
            agent_upvotes=10,
        )
        content = 0.3 * 10  # search_content_score with no answer
        expected = 0.8 * (1.0 + math.log1p(content))
        score = search_score(text_relevance=0.8, question=q, best_answer=None)
        assert score == expected

    def test_zero_votes_gives_nonzero_score(self):
        q = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
        )
        score = search_score(text_relevance=0.9, question=q, best_answer=None)
        assert score == 0.9  # 0.9 * (1.0 + 0) = 0.9

    def test_voted_ranks_above_unvoted(self):
        q_unvoted = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
        )
        q_voted = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
            agent_upvotes=5,
        )
        score_unvoted = search_score(
            text_relevance=0.9,
            question=q_unvoted,
            best_answer=None,
        )
        score_voted = search_score(
            text_relevance=0.9,
            question=q_voted,
            best_answer=None,
        )
        assert score_voted > score_unvoted

    def test_high_text_relevance_beats_moderate_votes(self):
        q_relevant = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
        )
        q_voted = Question(
            title="T",
            body="B",
            created_by="x",
            created_by_type="agent",
            agent_upvotes=5,
        )
        score_relevant = search_score(
            text_relevance=0.9,
            question=q_relevant,
            best_answer=None,
        )
        score_voted = search_score(
            text_relevance=0.2,
            question=q_voted,
            best_answer=None,
        )
        assert score_relevant > score_voted

    def test_language_framework_bonus(self):
        score_no_match = text_relevance_score(
            fts_rank=0.5,
            tag_jaccard=0.5,
            language_match=False,
            framework_match=False,
        )
        score_with_match = text_relevance_score(
            fts_rank=0.5,
            tag_jaccard=0.5,
            language_match=True,
            framework_match=True,
        )
        assert score_with_match > score_no_match
