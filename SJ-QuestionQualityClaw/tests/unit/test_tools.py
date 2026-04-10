"""Tests for sjqqc.tools — mutation, validation, and export tools."""

import json

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


class TestUpdateAnswer:
    def test_changes_answer(self, block_q):
        orig = block_q.correct_answer_key
        new = "a" if orig != "a" else "b"
        updated, change = update_answer(block_q, new, strategy="test")
        assert updated.correct_answer_key == new
        assert change.old_value == orig
        assert change.strategy == "test"

    def test_invalid_key(self, block_q):
        with pytest.raises(ValueError, match="not in choices"):
            update_answer(block_q, "z")

    def test_immutable_original(self, block_q):
        orig = block_q.correct_answer_key
        update_answer(block_q, "a" if orig != "a" else "b")
        assert block_q.correct_answer_key == orig


class TestUpdateStem:
    def test_changes_stem(self, block_q):
        updated, change = update_stem(block_q, "New stem")
        assert updated.stem == "New stem"
        assert block_q.stem != "New stem"


class TestUpdateCode:
    def test_single_line(self, block_q):
        updated, change = update_code(block_q, 0, "# FIXED")
        assert updated.prompt.configuration.code[0] == "# FIXED"

    def test_out_of_range(self, block_q):
        with pytest.raises(ValueError, match="out of range"):
            update_code(block_q, 9999, "bad")


class TestUpdateCodeBlock:
    def test_same_length(self, block_q):
        updated, changes = update_code_block(block_q, 0, 2, ["a", "b", "c"])
        assert updated.prompt.configuration.code[0] == "a"
        assert len(changes) >= 1

    def test_preserves_other_lines(self, block_q):
        orig_10 = block_q.prompt.configuration.code[10]
        updated, _ = update_code_block(block_q, 0, 2, ["a", "b", "c"])
        assert updated.prompt.configuration.code[10] == orig_10


class TestUpdateChoice:
    def test_block_choice(self, block_q):
        updated, _ = update_choice(block_q, "a", {"start": 10, "end": 15})
        found = [c for c in updated.prompt.configuration.choices if c["key"] == "a"][0]
        assert found["start"] == 10

    def test_wrong_structure(self, block_q):
        with pytest.raises(ValueError, match="missing start/end"):
            update_choice(block_q, "a", {"code": ["x"]})


class TestReindexChoices:
    def test_block_reindex(self, block_q):
        orig = [c["start"] for c in block_q.prompt.configuration.choices]
        updated, changes = reindex_choices(block_q, 5)
        new = [c["start"] for c in updated.prompt.configuration.choices]
        for o, n in zip(orig, new, strict=True):
            assert n == o + 5

    def test_line_reindex(self, line_q):
        orig = [c["choice"] for c in line_q.prompt.configuration.choices]
        updated, _ = reindex_choices(line_q, -3)
        new = [c["choice"] for c in updated.prompt.configuration.choices]
        for o, n in zip(orig, new, strict=True):
            assert n == o - 3

    def test_generic_no_changes(self, generic_q):
        _, changes = reindex_choices(generic_q, 10)
        assert len(changes) == 0


class TestValidateStep:
    def test_unchanged(self, block_q):
        assert validate_step(block_q, block_q).passed

    def test_wrong_type_fails(self, block_q):
        bad = block_q.model_copy(deep=True)
        bad.prompt.typeId = "mc-line"
        assert not validate_step(block_q, bad).passed

    def test_empty_answers_fails(self, block_q):
        bad = block_q.model_copy(deep=True)
        bad.answers = []
        assert not validate_step(block_q, bad).passed


class TestValidateRoundtrip:
    def test_unmodified(self, block_q):
        assert validate_roundtrip(block_q, block_q)


class TestExport:
    def test_valid_json(self, block_q):
        json_str = export_platform_json(block_q)
        data = json.loads(json_str)
        assert "path" in data
        assert "state" not in data
        AssessmentQuestion(**data)
