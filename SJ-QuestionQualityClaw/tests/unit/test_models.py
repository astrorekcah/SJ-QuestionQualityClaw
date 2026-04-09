"""Unit tests for platform question models and feedback workflow."""

import json
from pathlib import Path

import pytest

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    FeedbackVerdict,
    PromptType,
    QuestionAuditTrail,
    ReviewEvent,
)

# ---------------------------------------------------------------------------
# Fixtures: load actual question files from Desktop
# ---------------------------------------------------------------------------

QUESTION_FILES = [
    Path("/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
         " _ Incorrect Authorization (2).json"),
    Path("/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
         " _ Missing Authentication for Critical Function (5).json"),
    Path("/home/m/Desktop/(Rust) Authentication and Authorization Issues"
         " _ Improper Privilege Management.json"),
    Path("/home/m/Desktop/(Rust) Software and Data Integrity Failures .json"),
]


def _load_question(path: Path) -> AssessmentQuestion:
    return AssessmentQuestion(**json.loads(path.read_text()))


def _available_questions() -> list[tuple[Path, AssessmentQuestion]]:
    """Load all available question files, skip missing ones."""
    results = []
    for p in QUESTION_FILES:
        if p.exists():
            results.append((p, _load_question(p)))
    return results


QUESTIONS = _available_questions()


# ---------------------------------------------------------------------------
# Platform schema parsing
# ---------------------------------------------------------------------------

class TestAssessmentQuestionParsing:
    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_loads_from_real_file(self, path, q):
        assert q.title
        assert q.path
        assert q.prompt.typeId in ("mc-block", "mc-code", "mc-line")
        assert len(q.prompt.configuration.choices) >= 2
        assert len(q.answers) >= 1

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_question_id_from_path(self, path, q):
        assert q.question_id  # non-empty
        assert "/" not in q.question_id  # last segment only

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_language_extracted(self, path, q):
        assert q.language in ("ruby", "rust")

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_correct_answer_is_valid_key(self, path, q):
        assert q.correct_answer_key in q.choice_keys()

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_code_is_non_empty(self, path, q):
        assert len(q.prompt.configuration.code) > 0
        assert q.code_text  # joined string

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_describe_choice_returns_content(self, path, q):
        for key in q.choice_keys():
            desc = q.describe_choice(key)
            assert desc
            # Sentinel pattern from describe_choice when key is missing
            assert not desc.startswith(f"Choice {key} (not found)")


class TestRoundTrip:
    """Verify questions survive export → re-import without data loss."""

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_platform_json_roundtrip(self, path, q):
        exported = q.to_platform_json()

        # Must contain exactly the platform fields
        assert "path" in exported
        assert "title" in exported
        assert "parameters" in exported
        assert "prompt" in exported
        assert "answers" in exported

        # Must NOT contain internal fields
        assert "state" not in exported
        assert "linear_ticket_id" not in exported
        assert "github_pr_url" not in exported

        # Re-parse must succeed
        reparsed = AssessmentQuestion(**exported)
        assert reparsed.path == q.path
        assert reparsed.title == q.title
        assert reparsed.prompt.typeId == q.prompt.typeId
        assert reparsed.choice_keys() == q.choice_keys()
        assert reparsed.correct_answer_key == q.correct_answer_key
        assert len(reparsed.prompt.configuration.code) == len(
            q.prompt.configuration.code
        )

    @pytest.mark.parametrize("path,q", QUESTIONS, ids=[p.stem for p, _ in QUESTIONS])
    def test_json_string_roundtrip(self, path, q):
        """Export to JSON string and back — simulates file write/read."""
        json_str = json.dumps(q.to_platform_json(), indent=2)
        reparsed = AssessmentQuestion(**json.loads(json_str))
        assert reparsed.to_platform_json() == q.to_platform_json()


class TestPromptTypes:
    def test_mc_block_choices_have_start_end(self):
        block_qs = [q for _, q in QUESTIONS if q.prompt_type == PromptType.MC_BLOCK]
        for q in block_qs:
            for c in q.prompt.configuration.choices:
                assert "start" in c
                assert "end" in c
                assert isinstance(c["start"], int)
                assert isinstance(c["end"], int)

    def test_mc_code_choices_have_code(self):
        code_qs = [q for _, q in QUESTIONS if q.prompt_type == PromptType.MC_CODE]
        for q in code_qs:
            for c in q.prompt.configuration.choices:
                assert "code" in c
                assert isinstance(c["code"], list)

    def test_mc_line_choices_have_choice(self):
        line_qs = [q for _, q in QUESTIONS if q.prompt_type == PromptType.MC_LINE]
        for q in line_qs:
            for c in q.prompt.configuration.choices:
                assert "choice" in c
                assert isinstance(c["choice"], int)


# ---------------------------------------------------------------------------
# Feedback workflow models
# ---------------------------------------------------------------------------

class TestFeedbackComment:
    def test_create_with_comment(self):
        fb = FeedbackComment(
            question_path="test/path",
            comment="The correct answer should be B, not C",
        )
        assert fb.id
        assert fb.comment
        assert fb.author == "reviewer"

    def test_with_target(self):
        fb = FeedbackComment(
            question_path="test/path",
            comment="Choice A is also correct",
            target_choice="a",
        )
        assert fb.target_choice == "a"


class TestFeedbackValidation:
    def test_create_valid(self):
        v = FeedbackValidation(
            feedback_id="fb1",
            question_path="test/path",
            verdict=FeedbackVerdict.VALID,
            confidence=0.95,
            reasoning="The feedback correctly identifies a flaw",
            suggested_action="update_answer",
        )
        assert v.verdict == FeedbackVerdict.VALID
        assert v.confidence == 0.95

    def test_all_verdicts(self):
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
            question_path="test/path",
            events=[
                ReviewEvent(event_type="feedback_received", summary="First"),
                ReviewEvent(event_type="validation_complete", summary="V1"),
                ReviewEvent(event_type="feedback_received", summary="Second"),
                ReviewEvent(event_type="revision_created", summary="R1"),
            ],
        )
        assert trail.feedback_count == 2
        assert trail.revision_count == 1
        assert trail.latest_event.event_type == "revision_created"
