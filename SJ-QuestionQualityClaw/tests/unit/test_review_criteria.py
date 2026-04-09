"""Unit tests for review criteria rubric."""

from config.review_criteria import (
    CLARITY,
    CORRECTNESS,
    DEFAULT_RUBRIC,
    DISTRACTOR_QUALITY,
    ReviewRubric,
)


class TestCriterion:
    def test_correctness_is_highest_weight(self):
        assert CORRECTNESS.weight == 3.0
        assert CORRECTNESS.weight > CLARITY.weight
        assert CORRECTNESS.weight > DISTRACTOR_QUALITY.weight

    def test_all_criteria_have_scoring_guide(self):
        for c in DEFAULT_RUBRIC.criteria:
            assert c.scoring_guide, f"{c.name} missing scoring guide"


class TestReviewRubric:
    def test_default_has_7_criteria(self):
        assert len(DEFAULT_RUBRIC.criteria) == 7

    def test_total_weight(self):
        assert DEFAULT_RUBRIC.total_weight == 12.0

    def test_thresholds(self):
        assert DEFAULT_RUBRIC.pass_threshold == 7.0
        assert DEFAULT_RUBRIC.revision_threshold == 5.0

    def test_to_prompt_section_contains_all_criteria(self):
        prompt = DEFAULT_RUBRIC.to_prompt_section()
        for c in DEFAULT_RUBRIC.criteria:
            assert c.name in prompt
            assert str(c.weight) in prompt

    def test_custom_rubric(self):
        rubric = ReviewRubric(
            criteria=[CORRECTNESS, CLARITY],
            pass_threshold=8.0,
            revision_threshold=6.0,
        )
        assert len(rubric.criteria) == 2
        assert rubric.total_weight == 5.0
        assert rubric.pass_threshold == 8.0
