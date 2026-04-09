"""Unit tests for domain models."""

from sjqqc.models import (
    BatchReport,
    BatchReportEntry,
    Choice,
    CriterionScore,
    Difficulty,
    Feedback,
    Question,
    QuestionState,
    QuestionType,
    Review,
    ReviewVerdict,
    RevisionHistory,
    RevisionHistoryEntry,
)


def _make_question(**overrides) -> Question:
    defaults = {
        "title": "Test Question",
        "body": "What is 2 + 2?",
        "question_type": QuestionType.MULTIPLE_CHOICE,
        "difficulty": Difficulty.BEGINNER,
        "domain": "math",
        "choices": [
            Choice(label="A", text="3", is_correct=False),
            Choice(label="B", text="4", is_correct=True),
            Choice(label="C", text="5", is_correct=False),
            Choice(label="D", text="22", is_correct=False),
        ],
    }
    defaults.update(overrides)
    return Question(**defaults)


def _make_review(question_id: str = "test123", **overrides) -> Review:
    defaults = {
        "question_id": question_id,
        "verdict": ReviewVerdict.PASS,
        "overall_score": 8.0,
        "summary": "Good question",
        "criterion_scores": [
            CriterionScore(criterion="correctness", score=9.0, weight=3.0, feedback="Correct"),
            CriterionScore(criterion="clarity", score=8.0, weight=2.0, feedback="Clear"),
        ],
        "suggestions": ["Minor: add explanation to choice D"],
    }
    defaults.update(overrides)
    return Review(**defaults)


class TestQuestion:
    def test_defaults(self):
        q = _make_question()
        assert q.state == QuestionState.DRAFT
        assert q.question_type == QuestionType.MULTIPLE_CHOICE
        assert len(q.choices) == 4
        assert q.id  # auto-generated

    def test_correct_choice(self):
        q = _make_question()
        correct = [c for c in q.choices if c.is_correct]
        assert len(correct) == 1
        assert correct[0].text == "4"

    def test_state_values(self):
        for state in QuestionState:
            assert isinstance(state.value, str)

    def test_external_refs_default_none(self):
        q = _make_question()
        assert q.github_pr_url is None
        assert q.linear_ticket_id is None


class TestReview:
    def test_basic(self):
        r = _make_review()
        assert r.verdict == ReviewVerdict.PASS
        assert r.overall_score == 8.0
        assert len(r.suggestions) == 1

    def test_criterion_scores(self):
        r = _make_review()
        assert len(r.criterion_scores) == 2
        assert r.criterion_scores[0].criterion == "correctness"


class TestFeedback:
    def test_consensus_all_pass(self):
        reviews = [_make_review(overall_score=8.0), _make_review(overall_score=7.5)]
        fb = Feedback(question_id="q1", reviews=reviews)
        fb.compute_consensus()
        assert fb.consensus_verdict == ReviewVerdict.PASS
        assert fb.average_score == 7.75

    def test_consensus_any_fail(self):
        reviews = [
            _make_review(verdict=ReviewVerdict.PASS, overall_score=8.0),
            _make_review(verdict=ReviewVerdict.FAIL, overall_score=3.0),
        ]
        fb = Feedback(question_id="q1", reviews=reviews)
        fb.compute_consensus()
        assert fb.consensus_verdict == ReviewVerdict.FAIL

    def test_consensus_mixed_revision(self):
        reviews = [
            _make_review(verdict=ReviewVerdict.PASS, overall_score=7.5),
            _make_review(verdict=ReviewVerdict.NEEDS_REVISION, overall_score=6.0),
        ]
        fb = Feedback(question_id="q1", reviews=reviews)
        fb.compute_consensus()
        assert fb.consensus_verdict == ReviewVerdict.NEEDS_REVISION

    def test_disputed_criteria(self):
        r1 = _make_review(criterion_scores=[
            CriterionScore(criterion="clarity", score=9.0, weight=2.0, feedback="Great"),
        ])
        r2 = _make_review(criterion_scores=[
            CriterionScore(criterion="clarity", score=5.0, weight=2.0, feedback="Poor"),
        ])
        fb = Feedback(question_id="q1", reviews=[r1, r2])
        fb.compute_consensus()
        assert "clarity" in fb.disputed_criteria

    def test_no_dispute_within_threshold(self):
        r1 = _make_review(criterion_scores=[
            CriterionScore(criterion="clarity", score=8.0, weight=2.0, feedback="Good"),
        ])
        r2 = _make_review(criterion_scores=[
            CriterionScore(criterion="clarity", score=7.0, weight=2.0, feedback="OK"),
        ])
        fb = Feedback(question_id="q1", reviews=[r1, r2])
        fb.compute_consensus()
        assert "clarity" not in fb.disputed_criteria


class TestBatchReport:
    def test_compute_stats(self):
        entries = [
            BatchReportEntry(
                question_id="q1", title="Q1", domain="math",
                verdict=ReviewVerdict.PASS, score=8.0,
            ),
            BatchReportEntry(
                question_id="q2", title="Q2", domain="math",
                verdict=ReviewVerdict.NEEDS_REVISION, score=6.0,
            ),
            BatchReportEntry(
                question_id="q3", title="Q3", domain="security",
                verdict=ReviewVerdict.FAIL, score=3.0,
            ),
        ]
        report = BatchReport(entries=entries)
        report.compute_stats()
        assert report.total == 3
        assert report.passed == 1
        assert report.needs_revision == 1
        assert report.failed == 1
        assert abs(report.pass_rate - 33.33) < 1
        assert abs(report.average_score - 5.67) < 0.1


class TestRevisionHistory:
    def test_trajectory(self):
        q = _make_question()
        r1 = _make_review(overall_score=5.0)
        r2 = _make_review(overall_score=7.5)
        history = RevisionHistory(
            question_id=q.id,
            entries=[
                RevisionHistoryEntry(version=1, question_snapshot=q, review=r1),
                RevisionHistoryEntry(version=2, question_snapshot=q, review=r2),
            ],
        )
        assert history.current_version == 2
        assert history.score_trajectory == [5.0, 7.5]
        assert history.latest_review.overall_score == 7.5
