"""IronClaw skill orchestrator — the pipeline that ties skills and tools together.

Flow:
  1. classify()         — LLM classifies feedback → ordered strategy list
  2. execute_strategy() — for each strategy, LLM produces targeted changes,
                          tools apply them, validate_step checks integrity
  3. assemble()         — build changelog, validate roundtrip, export platform JSON

Each strategy maps to a skill file in ironclaw/skills/fix_*.md and is
constrained to specific fields. The LLM only decides what to change within
that strategy's scope — tools.py does the actual mutation.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from loguru import logger

from sjqqc.changelog import build_changelog
from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    FieldChange,
    ImprovementChangelog,
    ImprovementStep,
    QuestionRevision,
)
from sjqqc.tools import (
    export_platform_json,
    update_answer,
    update_choice,
    update_code,
    update_stem,
    validate_roundtrip,
    validate_step,
)

# ---------------------------------------------------------------------------
# Strategy definitions — what each skill is allowed to do
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, dict[str, Any]] = {
    "fix_code": {
        "allowed_fields": ["code", "choices"],
        "system": (
            "You are QuestionQualityClaw executing the fix_code strategy.\n"
            "Given a question and feedback about code issues, identify the "
            "SPECIFIC code lines that need fixing.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"changes": [{"line": <index>, "new_line": "<fixed code>", '
            '"reason": "<why>"}], '
            '"line_count_changed": false, '
            '"notes": "<summary>"}'
        ),
    },
    "fix_answer": {
        "allowed_fields": ["answers"],
        "system": (
            "You are QuestionQualityClaw executing the fix_answer strategy.\n"
            "Given a question and feedback about the wrong answer, determine "
            "the correct answer key.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"new_answer": "<key>", "reason": "<why this is correct>", '
            '"notes": "<summary>"}'
        ),
    },
    "fix_stem": {
        "allowed_fields": ["stem"],
        "system": (
            "You are QuestionQualityClaw executing the fix_stem strategy.\n"
            "Given a question and feedback about stem issues, produce an "
            "improved stem.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"new_stem": "<improved text>", "reason": "<why>", '
            '"notes": "<summary>"}'
        ),
    },
    "fix_choices": {
        "allowed_fields": ["choices"],
        "system": (
            "You are QuestionQualityClaw executing the fix_choices strategy.\n"
            "Given a question and feedback about choice issues, produce "
            "improved choices. Keep the SAME keys and SAME structure.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"updates": [{"key": "<choice_key>", "content": {<new fields>}, '
            '"reason": "<why>"}], "notes": "<summary>"}'
        ),
    },
    "fix_scenario": {
        "allowed_fields": ["stem"],
        "system": (
            "You are QuestionQualityClaw executing the fix_scenario strategy.\n"
            "Given a question and feedback about unrealistic scenarios, "
            "rewrite the scenario portion of the stem.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"new_stem": "<improved text>", "reason": "<why>", '
            '"notes": "<summary>"}'
        ),
    },
    "fix_distractors": {
        "allowed_fields": ["choices"],
        "system": (
            "You are QuestionQualityClaw executing the fix_distractors strategy.\n"
            "Given a question and feedback about weak distractors, produce "
            "more plausible wrong choices. Do NOT change the correct answer's choice.\n\n"
            "You MUST respond with valid JSON:\n"
            '{"updates": [{"key": "<choice_key>", "content": {<new fields>}, '
            '"reason": "<why>"}], "notes": "<summary>"}'
        ),
    },
}

CLASSIFY_SYSTEM = """\
You are QuestionQualityClaw classifying feedback to determine which fix strategies to apply.

Available strategies (pick one or more, in execution order):
- fix_code: code has bugs, syntax errors, logic flaws
- fix_answer: the marked correct answer is wrong
- fix_choices: specific choices need revision (ambiguous, also correct, wrong)
- fix_stem: question stem is unclear or inaccurate
- fix_scenario: scenario is unrealistic or contrived
- fix_distractors: wrong choices are too obvious or implausible

Rules for ordering:
1. fix_code FIRST (code changes may shift line references)
2. fix_answer SECOND (highest priority correctness fix)
3. fix_choices THIRD (may depend on code)
4. fix_stem / fix_scenario / fix_distractors LAST

You MUST respond with valid JSON:
{"strategies": ["fix_code", "fix_answer", ...], "reasoning": "<why these strategies>"}
"""


# ---------------------------------------------------------------------------
# LLM Client (shared)
# ---------------------------------------------------------------------------

class LLMClient:
    """Async OpenRouter-compatible chat client. Shared across pipeline."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model or os.environ.get(
            "SELECTED_MODEL", "anthropic/claude-sonnet-4-20250514"
        )
        self.base_url = base_url or "https://openrouter.ai/api/v1"

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json()
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ValueError("Could not extract LLM content") from exc
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("LLM response not valid JSON: {}", text[:500])
            raise ValueError("LLM response not valid JSON") from exc


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _format_question(q: AssessmentQuestion) -> str:
    """Render question for LLM context (shared across pipeline steps)."""
    lines = [
        f"## {q.title}",
        f"Type: {q.prompt.typeId} | Language: {q.language}",
        "",
        "### Stem",
        q.stem,
        "",
        "### Code",
    ]
    for i, code_line in enumerate(q.prompt.configuration.code):
        lines.append(f"{i:>4}| {code_line}")
    lines.append("")
    lines.append("### Choices")
    for key in q.choice_keys():
        lines.append(f"**{key}**: {q.describe_choice(key)}")
    lines.append(f"\n### Correct Answer: {q.correct_answer_key}")
    return "\n".join(lines)


class ImprovementPipeline:
    """Orchestrates the IronClaw skill pipeline.

    classify() → execute strategies in order → assemble changelog → export.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    # ------------------------------------------------------------------
    # Step 1: Classify feedback into strategy list
    # ------------------------------------------------------------------

    async def classify(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
    ) -> list[str]:
        """Classify feedback and return ordered list of strategy names."""
        user_prompt = (
            f"{_format_question(question)}\n\n---\n\n"
            f"**Feedback**: {feedback.comment}\n"
        )
        if feedback.target_choice:
            user_prompt += f"**Target choice**: {feedback.target_choice}\n"

        parsed = await self.llm.chat(CLASSIFY_SYSTEM, user_prompt)
        strategies = parsed.get("strategies", [])

        # Filter to known strategies only
        valid = [s for s in strategies if s in STRATEGIES]
        if not valid:
            logger.warning(
                "No valid strategies from classification: {}",
                strategies,
            )
            # Fallback: use suggested_action heuristic
            valid = ["fix_stem"]

        logger.info("Classified → {}", valid)
        return valid

    # ------------------------------------------------------------------
    # Step 2: Execute a single strategy
    # ------------------------------------------------------------------

    async def execute_strategy(
        self,
        strategy_name: str,
        question: AssessmentQuestion,
        original: AssessmentQuestion,
        feedback: FeedbackComment,
    ) -> tuple[AssessmentQuestion, ImprovementStep]:
        """Run one strategy skill: LLM decides changes, tools apply them."""
        strategy = STRATEGIES[strategy_name]
        system = strategy["system"]

        user_prompt = (
            f"{_format_question(question)}\n\n---\n\n"
            f"**Feedback to address**: {feedback.comment}\n"
            f"**Your scope**: {', '.join(strategy['allowed_fields'])} only\n"
        )

        parsed = await self.llm.chat(system, user_prompt)
        changes: list[FieldChange] = []
        current = question

        # Apply changes based on strategy type
        if strategy_name in ("fix_code",):
            for change_spec in parsed.get("changes", []):
                line_idx = change_spec.get("line", 0)
                new_line = change_spec.get("new_line", "")
                reason = change_spec.get("reason", "")
                current, fc = update_code(
                    current, line_idx, new_line,
                    reason=reason, strategy=strategy_name,
                )
                fc.validated = True
                changes.append(fc)

        elif strategy_name == "fix_answer":
            new_key = parsed.get("new_answer", "")
            reason = parsed.get("reason", "")
            if new_key and new_key != current.correct_answer_key:
                current, fc = update_answer(
                    current, new_key,
                    reason=reason, strategy=strategy_name,
                )
                fc.validated = True
                changes.append(fc)

        elif strategy_name in ("fix_stem", "fix_scenario"):
            new_stem = parsed.get("new_stem", "")
            reason = parsed.get("reason", "")
            if new_stem and new_stem != current.stem:
                current, fc = update_stem(
                    current, new_stem,
                    reason=reason, strategy=strategy_name,
                )
                fc.validated = True
                changes.append(fc)

        elif strategy_name in ("fix_choices", "fix_distractors"):
            for upd in parsed.get("updates", []):
                key = upd.get("key", "")
                content = upd.get("content", {})
                reason = upd.get("reason", "")
                if key and content:
                    current, fc = update_choice(
                        current, key, content,
                        reason=reason, strategy=strategy_name,
                    )
                    fc.validated = True
                    changes.append(fc)

        # Validate after this step
        step_val = validate_step(original, current)

        step = ImprovementStep(
            strategy=strategy_name,
            fields_changed=changes,
            validation=step_val,
            notes=parsed.get("notes", ""),
        )

        if not step_val.passed:
            logger.warning(
                "Strategy {} failed validation: {}",
                strategy_name, step_val.errors,
            )
        else:
            logger.info(
                "Strategy {} applied: {} changes",
                strategy_name, len(changes),
            )

        return current, step

    # ------------------------------------------------------------------
    # Step 3: Assemble — changelog + roundtrip + export
    # ------------------------------------------------------------------

    def assemble(
        self,
        original: AssessmentQuestion,
        revised: AssessmentQuestion,
        steps: list[ImprovementStep],
        feedback: FeedbackComment,
    ) -> tuple[ImprovementChangelog, str]:
        """Build changelog, validate roundtrip, export platform JSON."""
        changelog = build_changelog(
            original, revised,
            steps=steps,
            feedback_id=feedback.id,
        )

        validate_roundtrip(original, revised)

        platform_json = export_platform_json(revised)

        logger.info(
            "Assembled: {} steps, {} field changes, summary={}",
            len(steps),
            changelog.total_fields_changed,
            changelog.summary,
        )
        return changelog, platform_json

    # ------------------------------------------------------------------
    # Full pipeline: classify → execute → assemble
    # ------------------------------------------------------------------

    async def run(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
        validation: FeedbackValidation,
    ) -> QuestionRevision:
        """Run the full IronClaw pipeline.

        1. Classify feedback → strategy list
        2. Execute each strategy in order (tools + validation)
        3. Assemble changelog + export platform JSON

        Returns a QuestionRevision with the revised question, changelog,
        and platform-ready JSON.
        """
        logger.info(
            "Pipeline: processing feedback on '{}'",
            question.question_id,
        )

        # 1. Classify
        strategies = await self.classify(question, feedback)

        # 2. Execute strategies in order
        current = question
        steps: list[ImprovementStep] = []
        for strategy_name in strategies:
            current, step = await self.execute_strategy(
                strategy_name, current, question, feedback,
            )
            steps.append(step)
            # Stop if validation failed
            if not step.validation.passed:
                logger.warning(
                    "Pipeline stopped: {} failed validation",
                    strategy_name,
                )
                break

        # 3. Assemble
        changelog, platform_json = self.assemble(
            question, current, steps, feedback,
        )

        revision = QuestionRevision(
            question_path=question.path,
            feedback_id=feedback.id,
            validation_id=validation.id,
            original=question,
            revised=current,
            changes_made=[
                fc.reason for step in steps for fc in step.fields_changed
            ],
            rationale=f"Pipeline: {' → '.join(strategies)}",
            changelog=changelog,
        )

        logger.info(
            "Pipeline complete: {} strategies, {} changes, output={} chars",
            len(strategies),
            changelog.total_fields_changed,
            len(platform_json),
        )
        return revision
