"""Tests for sjqqc.changelog — field diff engine."""

from sjqqc.changelog import build_changelog, diff_fields
from sjqqc.models import (
    FieldChange,
    ImprovementChangelog,
    ImprovementStep,
    StepValidation,
)
from sjqqc.tools import update_answer, update_code, update_stem


class TestDiffFields:
    def test_identical(self, block_q):
        assert len(diff_fields(block_q, block_q)) == 0

    def test_stem_change(self, block_q):
        modified, _ = update_stem(block_q, "New")
        changes = diff_fields(block_q, modified)
        assert any(c.field_path == "prompt.configuration.prompt" for c in changes)

    def test_code_change(self, block_q):
        modified, _ = update_code(block_q, 0, "# changed")
        assert any("code[0]" in c.field_path for c in diff_fields(block_q, modified))

    def test_answer_change(self, block_q):
        new_key = "a" if block_q.correct_answer_key != "a" else "b"
        modified, _ = update_answer(block_q, new_key)
        assert any("answers" in c.field_path for c in diff_fields(block_q, modified))

    def test_multiple(self, block_q):
        q2, _ = update_stem(block_q, "New")
        q3, _ = update_code(q2, 0, "# changed")
        assert len(diff_fields(block_q, q3)) >= 2


class TestBuildChangelog:
    def test_with_steps(self, block_q):
        steps = [
            ImprovementStep(
                strategy="fix_stem",
                fields_changed=[FieldChange(
                    field_path="prompt.configuration.prompt",
                    strategy="fix_stem", validated=True,
                )],
                validation=StepValidation(passed=True),
            ),
        ]
        cl = build_changelog(block_q, block_q, steps=steps, feedback_id="fb1")
        assert cl.total_fields_changed == 1
        assert cl.strategies_used == ["fix_stem"]
        assert cl.all_steps_valid

    def test_without_steps(self, block_q):
        modified, _ = update_stem(block_q, "New")
        cl = build_changelog(block_q, modified)
        assert cl.total_fields_changed >= 1

    def test_summary_flags(self, block_q):
        new_key = "a" if block_q.correct_answer_key != "a" else "b"
        q2, _ = update_answer(block_q, new_key)
        q3, _ = update_code(q2, 0, "# changed")
        cl = build_changelog(block_q, q3)
        assert cl.summary["answer_changed"]
        assert cl.summary["code_changed"]

    def test_model_properties(self):
        cl = ImprovementChangelog(
            question_path="test",
            steps=[
                ImprovementStep(
                    strategy="fix_answer",
                    fields_changed=[FieldChange(field_path="answers[0].value")],
                    validation=StepValidation(passed=True),
                ),
                ImprovementStep(
                    strategy="fix_code",
                    fields_changed=[
                        FieldChange(field_path="prompt.configuration.code[5]"),
                        FieldChange(field_path="prompt.configuration.code[6]"),
                    ],
                    validation=StepValidation(passed=False, errors=["bad"]),
                ),
            ],
        )
        assert cl.total_fields_changed == 3
        assert not cl.all_steps_valid
        assert cl.strategies_used == ["fix_answer", "fix_code"]
