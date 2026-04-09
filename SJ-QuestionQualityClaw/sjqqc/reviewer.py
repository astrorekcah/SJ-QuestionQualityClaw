"""Question quality review engine — production-grade, multi-mode LLM analysis.

Modes:
  - single:      One-shot rubric evaluation
  - multi_pass:  N independent reviews → consensus Feedback with dispute detection
  - comparative: Diff a revised question against its original
  - batch:       Review a set of questions → aggregate BatchReport
  - revise:      Auto-generate an improved version of a question
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from typing import Any

import httpx
from loguru import logger

from config.review_criteria import DEFAULT_RUBRIC, ReviewRubric
from sjqqc.models import (
    BatchReport,
    BatchReportEntry,
    Choice,
    ComparisonResult,
    CriterionDelta,
    CriterionScore,
    Feedback,
    Question,
    Review,
    ReviewVerdict,
)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
You are QuestionQualityClaw, an expert assessment question quality reviewer.
You analyze questions for clarity, correctness, distractor quality, difficulty alignment,
coverage, fairness, and actionability.

You MUST respond with valid JSON matching this exact schema:
{
  "criterion_scores": [
    {"criterion": "<name>", "score": <0-10>, "feedback": "<specific feedback>"}
  ],
  "summary": "<2-3 sentence overall assessment>",
  "suggestions": ["<actionable suggestion 1>", ...],
  "revised_body": "<improved question text or null>",
  "revised_choices": [
    {"label": "A", "text": "...", "is_correct": false, "explanation": "..."}
  ] or null
}
"""

COMPARATIVE_SYSTEM_PROMPT = """\
You are QuestionQualityClaw comparing a REVISED question against its ORIGINAL version.
Determine whether the revision addressed the previous feedback and improved quality.

You MUST respond with valid JSON matching this exact schema:
{
  "improvements": ["<what got better>", ...],
  "regressions": ["<what got worse>", ...],
  "unresolved_issues": ["<original feedback not addressed>", ...],
  "revision_adequate": true/false,
  "notes": "<brief overall assessment of the revision>"
}
"""

REVISION_SYSTEM_PROMPT = """\
You are QuestionQualityClaw. Given a question and its review feedback, generate an
improved version that addresses the feedback while preserving the author's intent and
domain-specific terminology.

You MUST respond with valid JSON matching this exact schema:
{
  "revised_title": "<improved title>",
  "revised_body": "<improved question stem>",
  "revised_choices": [
    {"label": "A", "text": "...", "is_correct": true/false, "explanation": "..."}
  ] or null,
  "revised_correct_answer": "<for non-MCQ types>" or null,
  "changes_made": ["<description of each change>", ...],
  "rationale": "<why these changes address the feedback>"
}
"""


def _build_review_prompt(question: Question, rubric: ReviewRubric) -> str:
    """Build the user prompt for reviewing a question."""
    q_data = {
        "title": question.title,
        "body": question.body,
        "type": question.question_type.value,
        "difficulty": question.difficulty.value,
        "domain": question.domain,
        "tags": question.tags,
    }
    if question.choices:
        q_data["choices"] = [
            {
                "label": c.label,
                "text": c.text,
                "is_correct": c.is_correct,
                "explanation": c.explanation,
            }
            for c in question.choices
        ]
    if question.correct_answer:
        q_data["correct_answer"] = question.correct_answer
    if question.reference_material:
        q_data["reference_material"] = question.reference_material

    return (
        "Review the following assessment question using the rubric below.\n\n"
        f"## Question\n```json\n{json.dumps(q_data, indent=2)}\n```\n\n"
        f"## Rubric\n{rubric.to_prompt_section()}\n\n"
        "Respond with the JSON schema specified in your instructions. "
        "Be specific and actionable."
    )


def _build_comparative_prompt(
    original: Question,
    revised: Question,
    original_review: Review,
) -> str:
    """Build the prompt comparing original and revised question versions."""
    return (
        "## Original Question\n"
        f"**Title**: {original.title}\n"
        f"**Body**: {original.body}\n"
        f"**Choices**: {json.dumps([c.model_dump() for c in original.choices], indent=2) if original.choices else 'N/A'}\n\n"  # noqa: E501
        "## Original Review Feedback\n"
        f"**Score**: {original_review.overall_score}/10\n"
        f"**Verdict**: {original_review.verdict}\n"
        f"**Suggestions**: {json.dumps(original_review.suggestions)}\n\n"
        "## Revised Question\n"
        f"**Title**: {revised.title}\n"
        f"**Body**: {revised.body}\n"
        f"**Choices**: {json.dumps([c.model_dump() for c in revised.choices], indent=2) if revised.choices else 'N/A'}\n\n"  # noqa: E501
        "Analyze whether the revision adequately addressed the feedback."
    )


def _build_revision_prompt(question: Question, review: Review) -> str:
    """Build the prompt for auto-generating an improved question."""
    criterion_lines = "\n".join(
        f"- **{cs.criterion}** ({cs.score}/10): {cs.feedback}"
        for cs in review.criterion_scores
    )
    suggestion_lines = "\n".join(f"- {s}" for s in review.suggestions)

    return (
        "## Question to Improve\n"
        f"**Title**: {question.title}\n"
        f"**Body**: {question.body}\n"
        f"**Type**: {question.question_type.value}\n"
        f"**Difficulty**: {question.difficulty.value}\n"
        f"**Domain**: {question.domain}\n"
        f"**Choices**: {json.dumps([c.model_dump() for c in question.choices], indent=2) if question.choices else 'N/A'}\n\n"  # noqa: E501
        "## Review Feedback to Address\n"
        f"**Score**: {review.overall_score}/10 — **{review.verdict}**\n"
        f"**Summary**: {review.summary}\n"
        f"**Suggestions**:\n{suggestion_lines}\n\n"
        f"## Criterion Scores\n{criterion_lines}\n\n"
        "Generate an improved version that addresses ALL suggestions. "
        "Preserve the author's intent and domain terminology."
    )


# ---------------------------------------------------------------------------
# LLM Client (shared across all modes)
# ---------------------------------------------------------------------------

class _LLMClient:
    """Thin async wrapper around an OpenRouter-compatible chat API."""

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
        """Send a chat completion request and return parsed JSON content."""
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
        """Pull the JSON payload out of a chat completion response."""
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected LLM response structure: {}", raw)
            raise ValueError("Could not extract content from LLM response") from exc

        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("LLM response not valid JSON: {}", text[:500])
            raise ValueError("LLM response was not valid JSON") from exc


# ---------------------------------------------------------------------------
# Reviewer Engine
# ---------------------------------------------------------------------------

class QuestionReviewer:
    """Production-grade question quality reviewer.

    Supports five modes:
      review()       — single-pass rubric evaluation
      multi_pass()   — N reviews → consensus Feedback
      compare()      — diff original vs. revised question
      batch()        — review a list of questions → BatchReport
      revise()       — auto-generate improved question from feedback
    """

    def __init__(
        self,
        *,
        rubric: ReviewRubric | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.rubric = rubric or DEFAULT_RUBRIC
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
    # Single-pass review
    # ------------------------------------------------------------------

    async def review(self, question: Question) -> Review:
        """Run a single-pass quality review. Returns a structured Review."""
        logger.info("Reviewing question '{}' (id={})", question.title, question.id)

        parsed = await self._llm.chat(
            REVIEW_SYSTEM_PROMPT,
            _build_review_prompt(question, self.rubric),
        )
        review = self._parsed_to_review(question.id, parsed)

        logger.info(
            "Review complete: verdict={}, score={:.1f}",
            review.verdict, review.overall_score,
        )
        return review

    # ------------------------------------------------------------------
    # Multi-pass review → Feedback with consensus
    # ------------------------------------------------------------------

    async def multi_pass(
        self,
        question: Question,
        *,
        passes: int = 3,
        temperature_spread: float = 0.15,
    ) -> Feedback:
        """Run N independent reviews and aggregate into consensus Feedback.

        Temperature varies across passes (base ± spread) to get diverse
        evaluations from the same model.
        """
        logger.info(
            "Multi-pass review ({} passes) for '{}' (id={})",
            passes, question.title, question.id,
        )
        base_temp = 0.3
        prompt = _build_review_prompt(question, self.rubric)

        async def _single_pass(pass_idx: int) -> Review:
            temp = base_temp + (pass_idx - passes // 2) * temperature_spread
            temp = max(0.0, min(1.0, temp))
            parsed = await self._llm.chat(
                REVIEW_SYSTEM_PROMPT, prompt, temperature=temp,
            )
            return self._parsed_to_review(question.id, parsed)

        reviews = await asyncio.gather(
            *[_single_pass(i) for i in range(passes)],
            return_exceptions=True,
        )

        valid_reviews: list[Review] = []
        for i, r in enumerate(reviews):
            if isinstance(r, Exception):
                logger.warning("Pass {} failed: {}", i, r)
            else:
                valid_reviews.append(r)

        if not valid_reviews:
            raise RuntimeError("All review passes failed")

        feedback = Feedback(question_id=question.id, reviews=valid_reviews)
        feedback.compute_consensus()

        logger.info(
            "Multi-pass consensus: verdict={}, score={:.1f}, disputed={}",
            feedback.consensus_verdict, feedback.average_score, feedback.disputed_criteria,
        )
        return feedback

    # ------------------------------------------------------------------
    # Comparative review (original vs. revised)
    # ------------------------------------------------------------------

    async def compare(
        self,
        original: Question,
        revised: Question,
        original_review: Review,
    ) -> ComparisonResult:
        """Compare a revised question against its original + review."""
        logger.info("Comparative review for question {}", original.id)

        revised_review = await self.review(revised)

        comparison_data = await self._llm.chat(
            COMPARATIVE_SYSTEM_PROMPT,
            _build_comparative_prompt(original, revised, original_review),
        )

        orig_scores = {cs.criterion: cs.score for cs in original_review.criterion_scores}
        rev_scores = {cs.criterion: cs.score for cs in revised_review.criterion_scores}
        all_criteria = set(orig_scores) | set(rev_scores)
        criterion_deltas = [
            CriterionDelta(
                criterion=c,
                original_score=orig_scores.get(c, 0.0),
                revised_score=rev_scores.get(c, 0.0),
                delta=round(rev_scores.get(c, 0.0) - orig_scores.get(c, 0.0), 2),
            )
            for c in all_criteria
        ]

        result = ComparisonResult(
            question_id=original.id,
            original_score=original_review.overall_score,
            revised_score=revised_review.overall_score,
            score_delta=round(revised_review.overall_score - original_review.overall_score, 2),
            criterion_deltas=criterion_deltas,
            improvements=comparison_data.get("improvements", []),
            regressions=comparison_data.get("regressions", []),
            unresolved_issues=comparison_data.get("unresolved_issues", []),
            revision_adequate=comparison_data.get("revision_adequate", False),
            original_review=original_review,
            revised_review=revised_review,
        )

        logger.info(
            "Comparison: {:.1f} → {:.1f} (Δ{:+.1f}), adequate={}",
            result.original_score, result.revised_score,
            result.score_delta, result.revision_adequate,
        )
        return result

    # ------------------------------------------------------------------
    # Batch review
    # ------------------------------------------------------------------

    async def batch(
        self,
        questions: list[Question],
        *,
        concurrency: int = 3,
    ) -> BatchReport:
        """Review a batch of questions with controlled concurrency."""
        logger.info("Batch review: {} questions, concurrency={}", len(questions), concurrency)

        semaphore = asyncio.Semaphore(concurrency)
        all_suggestions: list[str] = []
        all_criterion_scores: dict[str, list[float]] = {}

        async def _review_one(q: Question) -> BatchReportEntry:
            async with semaphore:
                review = await self.review(q)
                all_suggestions.extend(review.suggestions)
                for cs in review.criterion_scores:
                    all_criterion_scores.setdefault(cs.criterion, []).append(cs.score)
                return BatchReportEntry(
                    question_id=q.id,
                    title=q.title,
                    domain=q.domain,
                    verdict=review.verdict,
                    score=review.overall_score,
                    top_issue=review.suggestions[0] if review.suggestions else "",
                )

        results = await asyncio.gather(
            *[_review_one(q) for q in questions],
            return_exceptions=True,
        )

        entries = [r for r in results if isinstance(r, BatchReportEntry)]
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning("Batch item {} failed: {}", i, r)

        report = BatchReport(entries=entries)
        report.compute_stats()

        issue_counts = Counter(all_suggestions)
        report.common_issues = [
            issue for issue, count in issue_counts.most_common(10) if count >= 2
        ]

        if all_criterion_scores:
            avg_by_criterion = {
                c: sum(scores) / len(scores)
                for c, scores in all_criterion_scores.items()
            }
            sorted_criteria = sorted(avg_by_criterion.items(), key=lambda x: x[1])
            report.weakest_criteria = [c for c, _ in sorted_criteria[:3]]

        logger.info(
            "Batch complete: {}/{} passed ({:.0f}%), avg score {:.1f}",
            report.passed, report.total, report.pass_rate, report.average_score,
        )
        return report

    # ------------------------------------------------------------------
    # Auto-revision generation
    # ------------------------------------------------------------------

    async def revise(self, question: Question, review: Review) -> Question:
        """Auto-generate an improved version of a question based on review feedback."""
        logger.info("Auto-revising question '{}' (id={})", question.title, question.id)

        parsed = await self._llm.chat(
            REVISION_SYSTEM_PROMPT,
            _build_revision_prompt(question, review),
            temperature=0.4,
        )

        revised = question.model_copy(deep=True)
        revised.title = parsed.get("revised_title", question.title)
        revised.body = parsed.get("revised_body", question.body)

        if parsed.get("revised_choices"):
            revised.choices = [
                Choice(
                    label=rc.get("label", ""),
                    text=rc.get("text", ""),
                    is_correct=rc.get("is_correct", False),
                    explanation=rc.get("explanation"),
                )
                for rc in parsed["revised_choices"]
            ]

        if parsed.get("revised_correct_answer"):
            revised.correct_answer = parsed["revised_correct_answer"]

        changes = parsed.get("changes_made", [])
        logger.info(
            "Revision generated: {} changes — {}",
            len(changes), parsed.get("rationale", ""),
        )
        return revised

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parsed_to_review(self, question_id: str, parsed: dict[str, Any]) -> Review:
        """Convert parsed LLM JSON into a Review object with weighted scoring."""
        rubric_map = {c.name: c for c in self.rubric.criteria}

        criterion_scores: list[CriterionScore] = []
        for cs in parsed.get("criterion_scores", []):
            name = cs.get("criterion", "")
            rubric_criterion = rubric_map.get(name)
            weight = rubric_criterion.weight if rubric_criterion else 1.0
            criterion_scores.append(CriterionScore(
                criterion=name,
                score=float(cs.get("score", 0)),
                weight=weight,
                feedback=cs.get("feedback", ""),
            ))

        total_weight = sum(cs.weight for cs in criterion_scores) or 1.0
        overall_score = sum(cs.score * cs.weight for cs in criterion_scores) / total_weight

        if overall_score >= self.rubric.pass_threshold:
            verdict = ReviewVerdict.PASS
        elif overall_score >= self.rubric.revision_threshold:
            verdict = ReviewVerdict.NEEDS_REVISION
        else:
            verdict = ReviewVerdict.FAIL

        revised_choices = None
        if parsed.get("revised_choices"):
            revised_choices = [
                Choice(
                    label=rc.get("label", ""),
                    text=rc.get("text", ""),
                    is_correct=rc.get("is_correct", False),
                    explanation=rc.get("explanation"),
                )
                for rc in parsed["revised_choices"]
            ]

        return Review(
            question_id=question_id,
            verdict=verdict,
            overall_score=round(overall_score, 2),
            criterion_scores=criterion_scores,
            summary=parsed.get("summary", ""),
            suggestions=parsed.get("suggestions", []),
            revised_body=parsed.get("revised_body"),
            revised_choices=revised_choices,
            reviewer_model=self.model,
            raw_llm_response=parsed,
        )
