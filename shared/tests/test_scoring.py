from acq_shared.models import Question, Answer
from acq_shared.scoring import (
    weighted_vote_score,
    search_content_score,
    search_score,
    rank_answers,
    text_relevance_score,
    DEFAULT_HUMAN_VOTE_WEIGHT,
)


class TestWeightedVoteScore:
    def test_agent_only(self):
        score = weighted_vote_score(
            agent_up=10, agent_down=2, human_up=0, human_down=0
        )
        assert score == 8  # 10 - 2

    def test_human_weighted(self):
        score = weighted_vote_score(
            agent_up=0, agent_down=0, human_up=2, human_down=0
        )
        assert score == 10  # 2 * 5

    def test_mixed(self):
        score = weighted_vote_score(
            agent_up=10, agent_down=2, human_up=1, human_down=1
        )
        assert score == 8  # (10-2) + (1*5 - 1*5)

    def test_custom_weight(self):
        score = weighted_vote_score(
            agent_up=0, agent_down=0, human_up=1, human_down=0,
            human_weight=10,
        )
        assert score == 10


class TestSearchContentScore:
    def test_question_only_no_answers(self):
        q = Question(
            title="T", body="B", created_by="x", created_by_type="agent",
            agent_upvotes=10, agent_downvotes=0,
        )
        score = search_content_score(q, best_answer=None)
        assert score == 0.3 * 10  # 0.3 * question_score, 0.7 * 0

    def test_with_best_answer(self):
        q = Question(
            title="T", body="B", created_by="x", created_by_type="agent",
            agent_upvotes=10, agent_downvotes=0,
        )
        a = Answer(
            question_id=q.id, body="Fix", created_by="x",
            created_by_type="agent", status="approved",
            agent_upvotes=20, agent_downvotes=0,
        )
        score = search_content_score(q, best_answer=a)
        assert score == 0.3 * 10 + 0.7 * 20


class TestRankAnswers:
    def test_pinned_first(self):
        a1 = Answer(
            question_id="q_1", body="A", created_by="x",
            created_by_type="agent", status="approved",
            agent_upvotes=100,
        )
        a2 = Answer(
            question_id="q_1", body="B", created_by="x",
            created_by_type="agent", status="approved",
            agent_upvotes=1,
        )
        ranked = rank_answers([a1, a2], pinned_id=a2.id)
        assert ranked[0].id == a2.id  # pinned wins despite fewer votes

    def test_vote_order(self):
        a1 = Answer(
            question_id="q_1", body="A", created_by="x",
            created_by_type="agent", status="approved",
            agent_upvotes=5,
        )
        a2 = Answer(
            question_id="q_1", body="B", created_by="x",
            created_by_type="agent", status="approved",
            agent_upvotes=10,
        )
        ranked = rank_answers([a1, a2], pinned_id=None)
        assert ranked[0].id == a2.id


class TestSearchScore:
    def test_combines_relevance_and_content(self):
        q = Question(
            title="T", body="B", created_by="x", created_by_type="agent",
            agent_upvotes=10,
        )
        score = search_score(text_relevance=0.8, question=q, best_answer=None)
        expected = 0.8 * (0.3 * 10)  # 0.8 * 3.0 = 2.4
        assert score == expected

    def test_language_framework_bonus(self):
        score_no_match = text_relevance_score(
            fts_rank=0.5, tag_jaccard=0.5,
            language_match=False, framework_match=False,
        )
        score_with_match = text_relevance_score(
            fts_rank=0.5, tag_jaccard=0.5,
            language_match=True, framework_match=True,
        )
        assert score_with_match > score_no_match
