"""Feedback-driven question review engine.

Primary workflow:
  1. validate_feedback()  — Is the human comment technically correct?
  2. improve_question()   — Apply validated feedback to produce a revised question
  3. quality_check()      — Independent quality assessment (secondary mode)

Handles all platform question types: mc-block, mc-code, mc-line.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from loguru import logger

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    FeedbackVerdict,
    QuestionRevision,
)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

VALIDATE_FEEDBACK_SYSTEM = """\
You are QuestionQualityClaw, a technical reviewer for secure-coding assessment questions.
You receive a question (with code and choices) and a human feedback comment.
Your job: determine whether the feedback is TECHNICALLY CORRECT.

Analyze the code carefully. Consider the programming language, security context, and
whether the feedback identifies a real issue with the question, its answer, or its choices.

You MUST respond with valid JSON:
{
  "verdict": "valid" | "partially_valid" | "invalid" | "unclear",
  "confidence": 0.0-1.0,
  "reasoning": "<detailed technical analysis explaining your assessment>",
  "affected_areas": ["stem", "code", "choices", "answer", "scenario"],
  "requires_human_review": true/false,
  "suggested_action": "update_answer" | "revise_stem" | "revise_choices" | \
"revise_code" | "add_explanation" | "no_action" | "needs_discussion"
}
"""

IMPROVE_QUESTION_SYSTEM = """\
You are QuestionQualityClaw. Given an assessment question and validated feedback,
produce an improved version that addresses the feedback.

CRITICAL: The output must be re-uploadable to the platform without modification.
You must return the COMPLETE question in the EXACT platform JSON schema.

Rules:
- Return the full question object with path, title, parameters, prompt, and answers
- The prompt.typeId MUST stay the same
- The prompt.configuration.choices MUST keep the exact same structure per typeId:
  - mc-block: each choice has {"key": "x", "start": N, "end": N}
  - mc-code: each choice has {"key": "x", "code": ["line1", ...]}
  - mc-line: each choice has {"key": "x", "choice": N}
- Keep the same number of choices with the same keys (a, b, c, d)
- The answers array format: [{"value": "<key>"}]
- If codeLine exists in the original, preserve it
- Do NOT add any extra fields the platform doesn't expect
- Do NOT change the path or parameters

You MUST respond with valid JSON:
{
  "revised_question": { <full platform question JSON> },
  "changes_made": ["<description of change 1>", ...],
  "rationale": "<why these changes address the feedback>"
}
"""

QUALITY_CHECK_SYSTEM = """\
You are QuestionQualityClaw performing an independent quality check on a
secure-coding assessment question. Evaluate the question on these dimensions:

1. **Technical accuracy**: Is the marked answer correct? Is the code realistic?
2. **Stem clarity**: Is the scenario clear and unambiguous?
3. **Choice quality**: Are wrong choices plausible? Is there exactly one correct answer?
4. **Code quality**: Is the code syntactically valid and realistic for the language?
5. **Difficulty calibration**: Does it test what it claims to test?

You MUST respond with valid JSON:
{
  "overall_score": 0-10,
  "technical_accuracy": {"score": 0-10, "notes": "..."},
  "stem_clarity": {"score": 0-10, "notes": "..."},
  "choice_quality": {"score": 0-10, "notes": "..."},
  "code_quality": {"score": 0-10, "notes": "..."},
  "difficulty_calibration": {"score": 0-10, "notes": "..."},
  "issues_found": ["<issue 1>", ...],
  "verdict": "pass" | "needs_revision" | "fail"
}
"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _format_question_for_llm(q: AssessmentQuestion) -> str:
    """Render a question into a text block the LLM can analyze."""
    lines = [
        f"## Question: {q.title}",
        f"**Type**: {q.prompt.typeId}",
        f"**Language**: {q.language}",
        f"**Path**: {q.path}",
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
        lines.append(f"**{key.upper()}**: {q.describe_choice(key)}")
        lines.append("")

    lines.append(f"### Correct Answer: {q.correct_answer_key}")
    return "\n".join(lines)


def _build_validate_prompt(
    q: AssessmentQuestion,
    feedback: FeedbackComment,
) -> str:
    return (
        f"{_format_question_for_llm(q)}\n\n"
        "---\n\n"
        "## Feedback to Validate\n"
        f"**Author**: {feedback.author}\n"
        f"**Comment**: {feedback.comment}\n"
        + (
            f"**Target choice**: {feedback.target_choice}\n"
            if feedback.target_choice else ""
        )
        + (
            f"**Target lines**: {feedback.target_lines}\n"
            if feedback.target_lines else ""
        )
        + "\nIs this feedback technically correct? Analyze carefully."
    )


def _build_improve_prompt(
    q: AssessmentQuestion,
    feedback: FeedbackComment,
    validation: FeedbackValidation,
) -> str:
    # Include the raw platform JSON so the LLM sees the exact format to preserve
    platform_json = json.dumps(q.to_platform_json(), indent=2)
    return (
        f"## Original Question (exact platform format — preserve this structure)\n"
        f"```json\n{platform_json}\n```\n\n"
        f"## Human-Readable View\n"
        f"{_format_question_for_llm(q)}\n\n"
        "---\n\n"
        "## Validated Feedback\n"
        f"**Comment**: {feedback.comment}\n"
        f"**Verdict**: {validation.verdict}\n"
        f"**Reasoning**: {validation.reasoning}\n"
        f"**Suggested action**: {validation.suggested_action}\n"
        f"**Affected areas**: {', '.join(validation.affected_areas)}\n\n"
        "Return the COMPLETE revised question in the `revised_question` field "
        "using the EXACT same JSON structure shown above. "
        "The output must be directly uploadable to the platform."
    )


def _build_quality_check_prompt(q: AssessmentQuestion) -> str:
    return (
        f"{_format_question_for_llm(q)}\n\n"
        "Perform a thorough quality check. Be specific about any issues found."
    )


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class _LLMClient:
    """Async wrapper around an OpenRouter-compatible chat API."""

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

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
            logger.error("Unexpected LLM response: {}", raw)
            raise ValueError("Could not extract LLM content") from exc

        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [
                ln for ln in lines
                if not ln.strip().startswith("```")
            ]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("LLM response not valid JSON: {}", text[:500])
            raise ValueError("LLM response not valid JSON") from exc


# ---------------------------------------------------------------------------
# Round-trip validation
# ---------------------------------------------------------------------------

def _validate_platform_roundtrip(
    original: AssessmentQuestion,
    revised: AssessmentQuestion,
) -> None:
    """Validate that the revised question can round-trip through platform JSON.

    Raises ValueError if the revised question has structural problems
    that would prevent re-upload.
    """
    # 1. Export to platform JSON and re-parse
    exported = revised.to_platform_json()
    try:
        reparsed = AssessmentQuestion(**exported)
    except Exception as exc:
        raise ValueError(
            f"Revised question fails round-trip parse: {exc}"
        ) from exc

    # 2. Verify structural invariants
    errors: list[str] = []

    if reparsed.prompt.typeId != original.prompt.typeId:
        errors.append(
            f"typeId changed: {original.prompt.typeId} → {reparsed.prompt.typeId}"
        )

    orig_keys = original.choice_keys()
    rev_keys = reparsed.choice_keys()
    if orig_keys != rev_keys:
        errors.append(f"choice keys changed: {orig_keys} → {rev_keys}")

    # Verify choice structure matches typeId
    for c in reparsed.prompt.configuration.choices:
        if original.prompt_type.value == "mc-block":
            if "start" not in c or "end" not in c:
                errors.append(f"mc-block choice {c.get('key')} missing start/end")
        elif original.prompt_type.value == "mc-line":
            if "choice" not in c:
                errors.append(f"mc-line choice {c.get('key')} missing choice field")
        elif original.prompt_type.value == "mc-code" and "code" not in c:
                errors.append(f"mc-code choice {c.get('key')} missing code field")

    if not reparsed.answers:
        errors.append("answers array is empty")

    if errors:
        raise ValueError(
            "Revised question has structural problems:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    logger.debug("Round-trip validation passed for {}", original.question_id)


# ---------------------------------------------------------------------------
# Reviewer Engine
# ---------------------------------------------------------------------------

class QuestionReviewer:
    """Feedback-driven question review engine.

    Primary workflow:
      validate_feedback()  — assess if a human comment is correct
      improve_question()   — apply validated feedback to revise question
      quality_check()      — independent quality assessment
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        _api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        _model = model or os.environ.get(
            "SELECTED_MODEL", "anthropic/claude-sonnet-4-20250514"
        )
        _base_url = base_url or "https://openrouter.ai/api/v1"
        self._llm = _LLMClient(_api_key, _model, _base_url)

    @property
    def model(self) -> str:
        return self._llm.model

    # ------------------------------------------------------------------
    # 1. Validate feedback
    # ------------------------------------------------------------------

    async def validate_feedback(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
    ) -> FeedbackValidation:
        """Assess whether a human feedback comment is technically correct.

        Returns a FeedbackValidation with verdict, confidence, and reasoning.
        """
        logger.info(
            "Validating feedback on '{}': '{}'",
            question.question_id,
            feedback.comment[:80],
        )

        parsed = await self._llm.chat(
            VALIDATE_FEEDBACK_SYSTEM,
            _build_validate_prompt(question, feedback),
        )

        validation = FeedbackValidation(
            feedback_id=feedback.id,
            question_path=question.path,
            verdict=FeedbackVerdict(parsed.get("verdict", "unclear")),
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", ""),
            affected_areas=parsed.get("affected_areas", []),
            requires_human_review=parsed.get(
                "requires_human_review", False
            ),
            suggested_action=parsed.get("suggested_action", "no_action"),
            raw_llm_response=parsed,
        )

        logger.info(
            "Validation: {} (confidence={:.0%}), action={}",
            validation.verdict,
            validation.confidence,
            validation.suggested_action,
        )
        return validation

    # ------------------------------------------------------------------
    # 2. Improve question based on validated feedback
    # ------------------------------------------------------------------

    async def improve_question(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
        validation: FeedbackValidation,
    ) -> QuestionRevision:
        """Improve a question using the IronClaw skill pipeline.

        Delegates to ImprovementPipeline which:
        1. Classifies feedback → picks strategy skills
        2. Executes each strategy (LLM decides, tools apply + validate)
        3. Assembles changelog + exports platform-exact JSON

        Only call when validation.verdict is 'valid' or 'partially_valid'.
        """
        from sjqqc.pipeline import ImprovementPipeline, LLMClient

        pipeline = ImprovementPipeline(
            llm=LLMClient(
                api_key=self._llm.api_key,
                model=self._llm.model,
                base_url=self._llm.base_url,
            )
        )
        return await pipeline.run(question, feedback, validation)

    # ------------------------------------------------------------------
    # 3. Independent quality check
    # ------------------------------------------------------------------

    async def quality_check(
        self,
        question: AssessmentQuestion,
    ) -> dict[str, Any]:
        """Run an independent quality assessment on a question.

        Returns raw structured scores and issues — not feedback-driven,
        useful for batch auditing or pre-publish checks.
        """
        logger.info(
            "Quality check on '{}'",
            question.question_id,
        )

        parsed = await self._llm.chat(
            QUALITY_CHECK_SYSTEM,
            _build_quality_check_prompt(question),
        )

        logger.info(
            "Quality check: score={}, verdict={}",
            parsed.get("overall_score"),
            parsed.get("verdict"),
        )
        return parsed

    # ------------------------------------------------------------------
    # Export helper
    # ------------------------------------------------------------------

    @staticmethod
    def export_revision(
        revision: QuestionRevision,
    ) -> str:
        """Export the revised question as platform-ready JSON.

        This is the string you upload back to the external platform.
        """
        return json.dumps(
            revision.revised.to_platform_json(), indent=2
        )

    # ------------------------------------------------------------------
    # Full pipeline: validate → improve (if valid)
    # ------------------------------------------------------------------

    async def process_feedback(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
        *,
        auto_improve: bool = True,
    ) -> tuple[
        FeedbackValidation, QuestionRevision | None
    ]:
        """End-to-end: validate feedback, then improve if valid.

        Returns (validation, revision_or_None).
        """
        validation = await self.validate_feedback(question, feedback)

        revision = None
        if auto_improve and validation.verdict in (
            FeedbackVerdict.VALID,
            FeedbackVerdict.PARTIALLY_VALID,
        ):
            revision = await self.improve_question(
                question, feedback, validation
            )

        return validation, revision
