"""Tests for sjqqc.changelog — field diff engine."""

import json
from pathlib import Path

from sjqqc.changelog import build_changelog, diff_fields
from sjqqc.models import (
    AssessmentQuestion,
    FieldChange,
    ImprovementChangelog,
    ImprovementStep,
    StepValidation,
)
from sjqqc.tools import update_answer, update_code, update_stem

BLOCK_Q_PATH = Path(
    "/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
    " _ Incorrect Authorization (2).json"
)


def _load() -> AssessmentQuestion:
    return AssessmentQuestion(**json.loads(BLOCK_Q_PATH.read_text()))


# ---------------------------------------------------------------------------
# diff_fields
# ---------------------------------------------------------------------------

class TestDiffFields:
    def test_identical_no_changes(self):
        q = _load()
        changes = diff_fields(q, q)
        assert len(changes) == 0

    def test_stem_change_detected(self):
        q = _load()
        modified, _ = update_stem(q, "New stem")
        changes = diff_fields(q, modified)
        stem_changes = [
            c for c in changes
            if c.field_path == "prompt.configuration.prompt"
        ]
        assert len(stem_changes) == 1
        assert stem_changes[0].old_value == q.stem
        assert stem_changes[0].new_value == "New stem"

    def test_code_change_detected(self):
        q = _load()
        modified, _ = update_code(q, 0, "# changed")
        changes = diff_fields(q, modified)
        code_changes = [
            c for c in changes
            if "code[0]" in c.field_path
        ]
        assert len(code_changes) == 1

    def test_answer_change_detected(self):
        q = _load()
        new_key = "a" if q.correct_answer_key != "a" else "b"
        modified, _ = update_answer(q, new_key)
        changes = diff_fields(q, modified)
        answer_changes = [
            c for c in changes if "answers" in c.field_path
        ]
        assert len(answer_changes) == 1

    def test_multiple_changes(self):
        q = _load()
        q2, _ = update_stem(q, "New stem")
        q3, _ = update_code(q2, 0, "# changed")
        changes = diff_fields(q, q3)
        assert len(changes) >= 2


# ---------------------------------------------------------------------------
# build_changelog
# ---------------------------------------------------------------------------

class TestBuildChangelog:
    def test_with_steps(self):
        q = _load()
        steps = [
            ImprovementStep(
                strategy="fix_stem",
                fields_changed=[
                    FieldChange(
                        field_path="prompt.configuration.prompt",
                        old_value="old",
                        new_value="new",
                        strategy="fix_stem",
                        validated=True,
                    )
                ],
                validation=StepValidation(passed=True),
            ),
        ]
        cl = build_changelog(q, q, steps=steps, feedback_id="fb1")
        assert cl.question_path == q.path
        assert cl.feedback_id == "fb1"
        assert cl.total_fields_changed == 1
        assert cl.strategies_used == ["fix_stem"]
        assert cl.all_steps_valid

    def test_without_steps_uses_diff(self):
        q = _load()
        modified, _ = update_stem(q, "New stem")
        cl = build_changelog(q, modified)
        assert cl.total_fields_changed >= 1
        assert cl.strategies_used == ["direct_revision"]

    def test_summary_flags(self):
        q = _load()
        new_key = "a" if q.correct_answer_key != "a" else "b"
        q2, _ = update_answer(q, new_key)
        q3, _ = update_code(q2, 0, "# changed")
        cl = build_changelog(q, q3)
        summary = cl.summary
        assert summary["answer_changed"] is True
        assert summary["code_changed"] is True

    def test_changelog_model_properties(self):
        cl = ImprovementChangelog(
            question_path="test",
            steps=[
                ImprovementStep(
                    strategy="fix_answer",
                    fields_changed=[
                        FieldChange(field_path="answers[0].value"),
                    ],
                    validation=StepValidation(passed=True),
                ),
                ImprovementStep(
                    strategy="fix_code",
                    fields_changed=[
                        FieldChange(
                            field_path="prompt.configuration.code[5]"
                        ),
                        FieldChange(
                            field_path="prompt.configuration.code[6]"
                        ),
                    ],
                    validation=StepValidation(passed=False, errors=["bad"]),
                ),
            ],
        )
        assert cl.total_fields_changed == 3
        assert not cl.all_steps_valid
        assert cl.strategies_used == ["fix_answer", "fix_code"]
        assert cl.summary["answer_changed"] is True
        assert cl.summary["code_changed"] is True
