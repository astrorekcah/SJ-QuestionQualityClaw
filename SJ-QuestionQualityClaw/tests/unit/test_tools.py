"""Tests for sjqqc.tools — mutation, validation, and export tools."""

import json
from pathlib import Path

import pytest

from sjqqc.models import AssessmentQuestion
from sjqqc.tools import (
    export_platform_json,
    reindex_choices,
    update_answer,
    update_choice,
    update_code,
    update_code_block,
    update_stem,
    validate_roundtrip,
    validate_step,
)

# Load a real question for testing
BLOCK_Q_PATH = Path(
    "/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
    " _ Incorrect Authorization (2).json"
)
LINE_Q_PATH = Path(
    "/home/m/Desktop/(Rust) Authentication and Authorization Issues"
    " _ Improper Privilege Management.json"
)
CODE_Q_PATH = Path(
    "/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
    " _ Missing Authentication for Critical Function (5).json"
)


def _load(path: Path) -> AssessmentQuestion:
    return AssessmentQuestion(**json.loads(path.read_text()))


@pytest.fixture
def block_q() -> AssessmentQuestion:
    return _load(BLOCK_Q_PATH)


@pytest.fixture
def line_q() -> AssessmentQuestion:
    return _load(LINE_Q_PATH)


@pytest.fixture
def code_q() -> AssessmentQuestion:
    return _load(CODE_Q_PATH)


# ---------------------------------------------------------------------------
# update_answer
# ---------------------------------------------------------------------------

class TestUpdateAnswer:
    def test_changes_answer(self, block_q):
        original_key = block_q.correct_answer_key
        new_key = "a" if original_key != "a" else "b"
        updated, change = update_answer(block_q, new_key, strategy="fix_answer")
        assert updated.correct_answer_key == new_key
        assert change.field_path == "answers[0].value"
        assert change.old_value == original_key
        assert change.new_value == new_key
        assert change.strategy == "fix_answer"

    def test_invalid_key_raises(self, block_q):
        with pytest.raises(ValueError, match="not in choices"):
            update_answer(block_q, "z")

    def test_original_unchanged(self, block_q):
        original_key = block_q.correct_answer_key
        update_answer(block_q, "a" if original_key != "a" else "b")
        assert block_q.correct_answer_key == original_key


# ---------------------------------------------------------------------------
# update_stem
# ---------------------------------------------------------------------------

class TestUpdateStem:
    def test_changes_stem(self, block_q):
        new_stem = "What is the vulnerability?"
        updated, change = update_stem(block_q, new_stem)
        assert updated.stem == new_stem
        assert change.field_path == "prompt.configuration.prompt"
        assert block_q.stem != new_stem  # original unchanged


# ---------------------------------------------------------------------------
# update_code
# ---------------------------------------------------------------------------

class TestUpdateCode:
    def test_changes_single_line(self, block_q):
        updated, change = update_code(block_q, 0, "# FIXED LINE")
        assert updated.prompt.configuration.code[0] == "# FIXED LINE"
        assert change.field_path == "prompt.configuration.code[0]"

    def test_out_of_range_raises(self, block_q):
        with pytest.raises(ValueError, match="out of range"):
            update_code(block_q, 9999, "bad")


class TestUpdateCodeBlock:
    def test_same_length_replacement(self, block_q):
        start, end = 0, 2
        new_lines = ["# line 0", "# line 1", "# line 2"]
        updated, changes = update_code_block(block_q, start, end, new_lines)
        for i, ln in enumerate(new_lines):
            assert updated.prompt.configuration.code[i] == ln
        assert len(changes) >= 1

    def test_preserves_other_lines(self, block_q):
        original_line_10 = block_q.prompt.configuration.code[10]
        updated, _ = update_code_block(block_q, 0, 2, ["a", "b", "c"])
        assert updated.prompt.configuration.code[10] == original_line_10


# ---------------------------------------------------------------------------
# update_choice
# ---------------------------------------------------------------------------

class TestUpdateChoice:
    def test_update_block_choice(self, block_q):
        updated, change = update_choice(
            block_q, "a", {"start": 10, "end": 15}
        )
        found = [
            c for c in updated.prompt.configuration.choices
            if c["key"] == "a"
        ][0]
        assert found["start"] == 10
        assert found["end"] == 15

    def test_invalid_key_raises(self, block_q):
        with pytest.raises(ValueError, match="not found"):
            update_choice(block_q, "z", {"start": 0, "end": 1})

    def test_wrong_structure_raises(self, block_q):
        # mc-block needs start/end, not code
        with pytest.raises(ValueError, match="missing start/end"):
            update_choice(block_q, "a", {"code": ["x"]})


# ---------------------------------------------------------------------------
# reindex_choices
# ---------------------------------------------------------------------------

class TestReindexChoices:
    def test_block_reindex(self, block_q):
        orig_starts = [
            c["start"]
            for c in block_q.prompt.configuration.choices
        ]
        updated, changes = reindex_choices(block_q, 5)
        new_starts = [
            c["start"]
            for c in updated.prompt.configuration.choices
        ]
        for orig, new in zip(orig_starts, new_starts, strict=True):
            assert new == orig + 5
        assert len(changes) == len(block_q.choice_keys())

    def test_line_reindex(self, line_q):
        orig_lines = [
            c["choice"]
            for c in line_q.prompt.configuration.choices
        ]
        updated, changes = reindex_choices(line_q, -3)
        new_lines = [
            c["choice"]
            for c in updated.prompt.configuration.choices
        ]
        for orig, new in zip(orig_lines, new_lines, strict=True):
            assert new == orig - 3

    def test_code_type_no_changes(self, code_q):
        """mc-code choices don't have line references to reindex."""
        updated, changes = reindex_choices(code_q, 10)
        assert len(changes) == 0


# ---------------------------------------------------------------------------
# validate_step
# ---------------------------------------------------------------------------

class TestValidateStep:
    def test_unchanged_passes(self, block_q):
        result = validate_step(block_q, block_q)
        assert result.passed

    def test_changed_answer_passes(self, block_q):
        updated, _ = update_answer(block_q, "a")
        result = validate_step(block_q, updated)
        assert result.passed

    def test_wrong_type_fails(self, block_q):
        bad = block_q.model_copy(deep=True)
        bad.prompt.typeId = "mc-line"
        result = validate_step(block_q, bad)
        assert not result.passed
        assert any("typeId" in e for e in result.errors)

    def test_empty_answers_fails(self, block_q):
        bad = block_q.model_copy(deep=True)
        bad.answers = []
        result = validate_step(block_q, bad)
        assert not result.passed

    def test_line_count_change_warns(self, block_q):
        modified = block_q.model_copy(deep=True)
        modified.prompt.configuration.code.append("# extra")
        result = validate_step(block_q, modified)
        assert result.passed  # warning, not error
        assert len(result.warnings) >= 1


# ---------------------------------------------------------------------------
# validate_roundtrip
# ---------------------------------------------------------------------------

class TestValidateRoundtrip:
    def test_unmodified_passes(self, block_q):
        assert validate_roundtrip(block_q, block_q)

    def test_valid_modification_passes(self, block_q):
        updated, _ = update_stem(block_q, "New stem text")
        assert validate_roundtrip(block_q, updated)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

class TestExport:
    def test_exports_valid_json(self, block_q):
        json_str = export_platform_json(block_q)
        data = json.loads(json_str)
        assert "path" in data
        assert "state" not in data  # internal field stripped
        # Re-parseable
        reparsed = AssessmentQuestion(**data)
        assert reparsed.path == block_q.path
