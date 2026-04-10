"""End-to-end pipeline tests with mocked LLM responses."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from sjqqc.llm import LLMClient
from sjqqc.models import (
    FeedbackComment,
    FeedbackValidation,
    FeedbackVerdict,
    ImprovementStep,
    StepValidation,
)
from sjqqc.pipeline import ImprovementPipeline
from sjqqc.tools import update_answer
from tests.conftest import load_fixture


def _q():
    return load_fixture("mc-block")


class TestClassify:
    @pytest.mark.asyncio
    async def test_answer_feedback(self):
        q = _q()
        fb = FeedbackComment(question_path=q.path, comment="Answer should be D")
        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", new_callable=AsyncMock, return_value={
            "strategies": ["fix_answer"], "reasoning": "test",
        }):
            strategies = await pipeline.classify(q, fb)
        assert "fix_answer" in strategies

    @pytest.mark.asyncio
    async def test_filters_unknown(self):
        q = _q()
        fb = FeedbackComment(question_path=q.path, comment="test")
        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", new_callable=AsyncMock, return_value={
            "strategies": ["fix_answer", "nonexistent"], "reasoning": "test",
        }):
            strategies = await pipeline.classify(q, fb)
        assert "nonexistent" not in strategies


class TestExecuteStrategy:
    @pytest.mark.asyncio
    async def test_fix_answer(self):
        q = _q()
        fb = FeedbackComment(question_path=q.path, comment="Answer should be a")
        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", new_callable=AsyncMock, return_value={
            "new_answer": "a", "reason": "A is correct", "notes": "changed",
        }):
            updated, step = await pipeline.execute_strategy("fix_answer", q, q, fb)
        assert updated.correct_answer_key == "a"
        assert step.validation.passed

    @pytest.mark.asyncio
    async def test_fix_code(self):
        q = _q()
        fb = FeedbackComment(question_path=q.path, comment="Fix line 0")
        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", new_callable=AsyncMock, return_value={
            "changes": [{"line": 0, "new_line": "# fixed", "reason": "test"}],
            "line_count_changed": False, "notes": "fixed",
        }):
            updated, step = await pipeline.execute_strategy("fix_code", q, q, fb)
        assert updated.prompt.configuration.code[0] == "# fixed"


class TestAssemble:
    def test_produces_changelog_and_json(self):
        q = _q()
        updated, fc = update_answer(q, "a", strategy="fix_answer")
        step = ImprovementStep(
            strategy="fix_answer",
            fields_changed=[fc],
            validation=StepValidation(passed=True),
        )
        fb = FeedbackComment(question_path=q.path, comment="test")
        pipeline = ImprovementPipeline()
        changelog, platform_json = pipeline.assemble(q, updated, [step], fb)
        assert changelog.total_fields_changed == 1
        data = json.loads(platform_json)
        assert "path" in data
        assert "state" not in data


class TestPipelineRun:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        q = _q()
        fb = FeedbackComment(question_path=q.path, comment="Answer should be D")
        validation = FeedbackValidation(
            feedback_id=fb.id, question_path=q.path,
            verdict=FeedbackVerdict.VALID, confidence=0.95,
            reasoning="Correct",
        )
        call_count = 0

        async def mock_chat(self, system, user, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"strategies": ["fix_answer"], "reasoning": "test"}
            return {"new_answer": "d", "reason": "D is correct", "notes": "changed"}

        pipeline = ImprovementPipeline()
        with patch.object(LLMClient, "chat", mock_chat):
            revision = await pipeline.run(q, fb, validation)

        assert revision.revised.correct_answer_key == "d"
        assert revision.changelog is not None
        assert revision.changelog.summary["answer_changed"]
        assert revision.revised.to_platform_json()["path"] == q.path
