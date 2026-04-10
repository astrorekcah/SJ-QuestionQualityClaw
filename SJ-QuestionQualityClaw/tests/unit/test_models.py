"""Unit tests for platform question models and feedback workflow."""

import json

import pytest

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    FeedbackVerdict,
    QuestionAuditTrail,
    ReviewEvent,
)
from tests.conftest import ALL_FIXTURES


class TestAssessmentQuestionParsing:
    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_loads(self, name, q):
        assert q.title
        assert q.path
        assert q.prompt.typeId in ("mc-block", "mc-code", "mc-line", "mc-generic")
        assert len(q.prompt.configuration.choices) >= 2
        assert len(q.answers) >= 1

    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_question_id(self, name, q):
        assert q.question_id
        assert "/" not in q.question_id

    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_correct_answer_valid(self, name, q):
        assert q.correct_answer_key in q.choice_keys()

    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_describe_choice(self, name, q):
        for key in q.choice_keys():
            desc = q.describe_choice(key)
            assert desc
            assert not desc.startswith(f"Choice {key} (not found)")


class TestRoundTrip:
    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_platform_json_roundtrip(self, name, q):
        exported = q.to_platform_json()
        assert "state" not in exported
        reparsed = AssessmentQuestion(**exported)
        assert reparsed.to_platform_json() == exported

    @pytest.mark.parametrize("name,q", ALL_FIXTURES, ids=[n for n, _ in ALL_FIXTURES])
    def test_string_roundtrip(self, name, q):
        json_str = json.dumps(q.to_platform_json(), indent=2)
        reparsed = AssessmentQuestion(**json.loads(json_str))
        assert reparsed.to_platform_json() == q.to_platform_json()


class TestPromptTypes:
    def test_mc_block_structure(self, block_q):
        for c in block_q.prompt.configuration.choices:
            assert "start" in c and "end" in c

    def test_mc_code_structure(self, code_q):
        for c in code_q.prompt.configuration.choices:
            assert "code" in c

    def test_mc_line_structure(self, line_q):
        for c in line_q.prompt.configuration.choices:
            assert "choice" in c

    def test_mc_generic_structure(self, generic_q):
        for c in generic_q.prompt.configuration.choices:
            assert "choice" in c


class TestFeedbackModels:
    def test_feedback_comment(self):
        fb = FeedbackComment(
            question_path="test/path",
            comment="The correct answer should be B",
        )
        assert fb.id
        assert fb.author == "reviewer"

    def test_feedback_validation_verdicts(self):
        for verdict in FeedbackVerdict:
            v = FeedbackValidation(
                feedback_id="fb1",
                question_path="test/path",
                verdict=verdict,
                confidence=0.5,
                reasoning="test",
            )
            assert v.verdict == verdict


class TestAuditTrail:
    def test_counts(self):
        trail = QuestionAuditTrail(
            question_path="test",
            events=[
                ReviewEvent(event_type="feedback_received"),
                ReviewEvent(event_type="validation_complete"),
                ReviewEvent(event_type="feedback_received"),
                ReviewEvent(event_type="revision_created"),
            ],
        )
        assert trail.feedback_count == 2
        assert trail.revision_count == 1
