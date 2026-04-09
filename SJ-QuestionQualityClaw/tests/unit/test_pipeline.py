"""End-to-end pipeline tests with mocked LLM responses."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    FeedbackVerdict,
)
from sjqqc.pipeline import ImprovementPipeline, LLMClient

BLOCK_Q_PATH = Path(
    "/home/m/Desktop/(Ruby) Authentication and Authorization Issues"
    " _ Incorrect Authorization (2).json"
)


def _load() -> AssessmentQuestion:
    return AssessmentQuestion(**json.loads(BLOCK_Q_PATH.read_text()))


def _mock_llm_response(content: dict) -> dict:
    """Wrap content in OpenRouter chat completion format."""
    return {
        "choices": [{
            "message": {"content": json.dumps(content)}
        }]
    }


# ---------------------------------------------------------------------------
# Pipeline.classify()
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.asyncio
    async def test_classify_answer_feedback(self):
        q = _load()
        fb = FeedbackComment(
            question_path=q.path,
            comment="The correct answer should be D, not C",
        )

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "strategies": ["fix_answer"],
                "reasoning": "Feedback about wrong answer",
            }
        ):
            strategies = await pipeline.classify(q, fb)

        assert "fix_answer" in strategies

    @pytest.mark.asyncio
    async def test_classify_code_and_answer(self):
        q = _load()
        fb = FeedbackComment(
            question_path=q.path,
            comment="Line 80 has a bug, so the answer should be D",
        )

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "strategies": ["fix_code", "fix_answer"],
                "reasoning": "Code bug affects answer",
            }
        ):
            strategies = await pipeline.classify(q, fb)

        assert strategies == ["fix_code", "fix_answer"]

    @pytest.mark.asyncio
    async def test_classify_filters_unknown_strategies(self):
        q = _load()
        fb = FeedbackComment(question_path=q.path, comment="test")

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "strategies": ["fix_answer", "nonexistent_strategy"],
                "reasoning": "test",
            }
        ):
            strategies = await pipeline.classify(q, fb)

        assert "fix_answer" in strategies
        assert "nonexistent_strategy" not in strategies


# ---------------------------------------------------------------------------
# Pipeline.execute_strategy()
# ---------------------------------------------------------------------------

class TestExecuteStrategy:
    @pytest.mark.asyncio
    async def test_fix_answer_strategy(self):
        q = _load()
        fb = FeedbackComment(question_path=q.path, comment="Answer should be a")

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "new_answer": "a",
                "reason": "Choice A is the correct authorization flaw",
                "notes": "Changed answer from c to a",
            }
        ):
            updated, step = await pipeline.execute_strategy(
                "fix_answer", q, q, fb
            )

        assert updated.correct_answer_key == "a"
        assert step.strategy == "fix_answer"
        assert step.validation.passed
        assert len(step.fields_changed) == 1
        assert step.fields_changed[0].strategy == "fix_answer"

    @pytest.mark.asyncio
    async def test_fix_code_strategy(self):
        q = _load()
        fb = FeedbackComment(question_path=q.path, comment="Fix line 0")

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "changes": [
                    {"line": 0, "new_line": "  require 'sinatra/base'", "reason": "Use base"},
                ],
                "line_count_changed": False,
                "notes": "Fixed require statement",
            }
        ):
            updated, step = await pipeline.execute_strategy(
                "fix_code", q, q, fb
            )

        assert updated.prompt.configuration.code[0] == "  require 'sinatra/base'"
        assert step.strategy == "fix_code"
        assert step.validation.passed

    @pytest.mark.asyncio
    async def test_fix_stem_strategy(self):
        q = _load()
        fb = FeedbackComment(question_path=q.path, comment="Stem is unclear")

        pipeline = ImprovementPipeline()
        with patch.object(
            LLMClient, "chat", new_callable=AsyncMock, return_value={
                "new_stem": "Improved question stem.",
                "reason": "Clarified the ask",
                "notes": "Rewrote stem",
            }
        ):
            updated, step = await pipeline.execute_strategy(
                "fix_stem", q, q, fb
            )

        assert updated.stem == "Improved question stem."
        assert step.validation.passed


# ---------------------------------------------------------------------------
# Pipeline.assemble()
# ---------------------------------------------------------------------------

class TestAssemble:
    def test_assemble_produces_changelog_and_json(self):
        q = _load()
        from sjqqc.models import ImprovementStep, StepValidation
        from sjqqc.tools import update_answer

        updated, fc = update_answer(q, "a", strategy="fix_answer")
        step = ImprovementStep(
            strategy="fix_answer",
            fields_changed=[fc],
            validation=StepValidation(passed=True),
        )
        fb = FeedbackComment(question_path=q.path, comment="test")

        pipeline = ImprovementPipeline()
        changelog, platform_json = pipeline.assemble(q, updated, [step], fb)

        # Changelog
        assert changelog.total_fields_changed == 1
        assert changelog.all_steps_valid
        assert changelog.summary["answer_changed"]

        # Platform JSON is valid and re-parseable
        data = json.loads(platform_json)
        assert "path" in data
        assert "state" not in data
        reparsed = AssessmentQuestion(**data)
        assert reparsed.correct_answer_key == "a"


# ---------------------------------------------------------------------------
# Pipeline.run() — full end-to-end
# ---------------------------------------------------------------------------

class TestPipelineRun:
    @pytest.mark.asyncio
    async def test_full_pipeline_answer_fix(self):
        q = _load()
        fb = FeedbackComment(
            question_path=q.path,
            comment="The answer should be D not C",
        )
        validation = FeedbackValidation(
            feedback_id=fb.id,
            question_path=q.path,
            verdict=FeedbackVerdict.VALID,
            confidence=0.95,
            reasoning="Feedback is correct",
            suggested_action="update_answer",
        )

        # Mock LLM: classify returns fix_answer, then fix_answer returns d
        call_count = 0

        async def mock_chat(self, system, user, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # classify
                return {
                    "strategies": ["fix_answer"],
                    "reasoning": "Answer correction needed",
                }
            else:  # fix_answer
                return {
                    "new_answer": "d",
                    "reason": "Choice D is correct",
                    "notes": "Changed answer",
                }

        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", mock_chat):
            revision = await pipeline.run(q, fb, validation)

        # Revised question has new answer
        assert revision.revised.correct_answer_key == "d"

        # Changelog tracks the change
        assert revision.changelog is not None
        assert revision.changelog.total_fields_changed == 1
        assert revision.changelog.summary["answer_changed"]
        assert revision.changelog.strategies_used == ["fix_answer"]

        # Platform JSON round-trips
        exported = revision.revised.to_platform_json()
        reparsed = AssessmentQuestion(**exported)
        assert reparsed.correct_answer_key == "d"
        assert reparsed.path == q.path
        assert reparsed.prompt.typeId == q.prompt.typeId

    @pytest.mark.asyncio
    async def test_full_pipeline_multi_strategy(self):
        q = _load()
        fb = FeedbackComment(
            question_path=q.path,
            comment="Line 0 has a bug and the answer should be a",
        )
        validation = FeedbackValidation(
            feedback_id=fb.id,
            question_path=q.path,
            verdict=FeedbackVerdict.VALID,
            confidence=0.9,
            reasoning="Both code and answer need fixing",
        )

        call_count = 0

        async def mock_chat(self, system, user, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # classify
                return {
                    "strategies": ["fix_code", "fix_answer"],
                    "reasoning": "Code and answer",
                }
            elif call_count == 2:  # fix_code
                return {
                    "changes": [
                        {"line": 0, "new_line": "  require 'sinatra/base'",
                         "reason": "Use base class"},
                    ],
                    "line_count_changed": False,
                    "notes": "Fixed import",
                }
            else:  # fix_answer
                return {
                    "new_answer": "a",
                    "reason": "A is correct",
                    "notes": "Changed answer",
                }

        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", mock_chat):
            revision = await pipeline.run(q, fb, validation)

        assert revision.revised.correct_answer_key == "a"
        assert revision.revised.prompt.configuration.code[0] == "  require 'sinatra/base'"
        assert revision.changelog.total_fields_changed == 2
        assert revision.changelog.strategies_used == ["fix_code", "fix_answer"]
        assert revision.changelog.summary["code_changed"]
        assert revision.changelog.summary["answer_changed"]
        assert revision.rationale == "Pipeline: fix_code → fix_answer"
