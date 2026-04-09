"""Batch quality assessment — score every question against the baseline.

Runs quality_check() across all questions and produces:
  - Per-question score card (pass/fail per dimension)
  - Bank-wide report (aggregate pass rates, weakest dimensions)
  - Improvement priority list (worst questions first)

This is the foundation for systematic, continuous quality improvement.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from sjqqc.models import AssessmentQuestion

# ---------------------------------------------------------------------------
# Quality report models
# ---------------------------------------------------------------------------

class DimensionResult(BaseModel):
    """Result for a single quality dimension."""

    name: str
    severity: str
    passed: bool
    score: float = Field(ge=0.0, le=10.0, default=0.0)
    notes: str = ""


class QuestionScoreCard(BaseModel):
    """Quality score card for one question."""

    question_id: str
    title: str
    type_id: str
    language: str
    path: str
    dimensions: list[DimensionResult] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    overall_score: float = 0.0
    verdict: str = "unknown"  # pass | needs_revision | fail

    @property
    def critical_failures(self) -> list[DimensionResult]:
        return [
            d for d in self.dimensions
            if not d.passed and d.severity == "critical"
        ]

    @property
    def major_failures(self) -> list[DimensionResult]:
        return [
            d for d in self.dimensions
            if not d.passed and d.severity == "major"
        ]

    @property
    def pass_rate(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(1 for d in self.dimensions if d.passed) / len(self.dimensions)

    @property
    def needs_improvement(self) -> bool:
        return len(self.critical_failures) > 0 or len(self.major_failures) > 0


class BankReport(BaseModel):
    """Aggregate quality report across all questions."""

    total_questions: int = 0
    score_cards: list[QuestionScoreCard] = Field(default_factory=list)

    @property
    def passing_questions(self) -> int:
        return sum(1 for sc in self.score_cards if sc.verdict == "pass")

    @property
    def failing_questions(self) -> int:
        return sum(
            1 for sc in self.score_cards if sc.verdict == "fail"
        )

    @property
    def bank_pass_rate(self) -> float:
        if not self.score_cards:
            return 0.0
        return self.passing_questions / len(self.score_cards)

    @property
    def average_score(self) -> float:
        if not self.score_cards:
            return 0.0
        return sum(sc.overall_score for sc in self.score_cards) / len(
            self.score_cards
        )

    @property
    def dimension_pass_rates(self) -> dict[str, float]:
        """Per-dimension pass rate across all questions."""
        dim_counts: dict[str, list[bool]] = {}
        for sc in self.score_cards:
            for d in sc.dimensions:
                dim_counts.setdefault(d.name, []).append(d.passed)
        return {
            name: sum(vals) / len(vals)
            for name, vals in dim_counts.items()
        }

    @property
    def weakest_dimensions(self) -> list[tuple[str, float]]:
        """Dimensions sorted by pass rate, weakest first."""
        rates = self.dimension_pass_rates
        return sorted(rates.items(), key=lambda x: x[1])

    @property
    def priority_queue(self) -> list[QuestionScoreCard]:
        """Questions sorted by severity: most critical failures first."""
        return sorted(
            [sc for sc in self.score_cards if sc.needs_improvement],
            key=lambda sc: (
                -len(sc.critical_failures),
                -len(sc.major_failures),
                sc.overall_score,
            ),
        )


# ---------------------------------------------------------------------------
# Offline quality checks (no LLM needed)
# ---------------------------------------------------------------------------

def check_structural_quality(q: AssessmentQuestion) -> list[DimensionResult]:
    """Run structural checks that don't need an LLM.

    These are deterministic, fast, and catch obvious issues.
    """
    results: list[DimensionResult] = []

    # answer_correctness: answer key exists in choices
    answer_key = q.correct_answer_key
    choice_keys = q.choice_keys()
    results.append(DimensionResult(
        name="answer_key_valid",
        severity="critical",
        passed=answer_key is not None and answer_key in choice_keys,
        score=10.0 if answer_key in choice_keys else 0.0,
        notes=(
            f"Answer '{answer_key}' is in choices {choice_keys}"
            if answer_key in choice_keys
            else f"Answer '{answer_key}' NOT in choices {choice_keys}"
        ),
    ))

    # choice_count: must have exactly 4 choices
    results.append(DimensionResult(
        name="choice_count",
        severity="critical",
        passed=len(choice_keys) == 4,
        score=10.0 if len(choice_keys) == 4 else 0.0,
        notes=f"{len(choice_keys)} choices (expected 4)",
    ))

    # code_present: non-generic must have code
    if q.prompt.typeId != "mc-generic":
        has_code = len(q.prompt.configuration.code) > 0
        results.append(DimensionResult(
            name="code_present",
            severity="critical",
            passed=has_code,
            score=10.0 if has_code else 0.0,
            notes=f"{len(q.prompt.configuration.code)} code lines",
        ))

    # stem_length: must be substantive
    stem_len = len(q.stem)
    stem_ok = stem_len >= 50
    results.append(DimensionResult(
        name="stem_length",
        severity="major",
        passed=stem_ok,
        score=min(10.0, stem_len / 30),
        notes=f"{stem_len} chars ({'OK' if stem_ok else 'too short'})",
    ))

    # choice_structure: matches typeId
    if q.prompt.typeId == "mc-block":
        for c in q.prompt.configuration.choices:
            if "start" not in c or "end" not in c:
                results.append(DimensionResult(
                    name="choice_structure",
                    severity="critical",
                    passed=False,
                    score=0.0,
                    notes=f"mc-block choice '{c.get('key')}' missing start/end",
                ))
                break
        else:
            results.append(DimensionResult(
                name="choice_structure",
                severity="critical",
                passed=True,
                score=10.0,
                notes="All choices have start/end",
            ))
    elif q.prompt.typeId == "mc-line":
        for c in q.prompt.configuration.choices:
            if "choice" not in c:
                results.append(DimensionResult(
                    name="choice_structure",
                    severity="critical",
                    passed=False,
                    score=0.0,
                    notes=f"mc-line choice '{c.get('key')}' missing choice field",
                ))
                break
        else:
            results.append(DimensionResult(
                name="choice_structure",
                severity="critical",
                passed=True,
                score=10.0,
                notes="All choices have line references",
            ))
    elif q.prompt.typeId == "mc-code":
        for c in q.prompt.configuration.choices:
            if "code" not in c:
                results.append(DimensionResult(
                    name="choice_structure",
                    severity="critical",
                    passed=False,
                    score=0.0,
                    notes=f"mc-code choice '{c.get('key')}' missing code field",
                ))
                break
        else:
            results.append(DimensionResult(
                name="choice_structure",
                severity="critical",
                passed=True,
                score=10.0,
                notes="All choices have code arrays",
            ))
    elif q.prompt.typeId == "mc-generic":
        for c in q.prompt.configuration.choices:
            if "choice" not in c:
                results.append(DimensionResult(
                    name="choice_structure",
                    severity="critical",
                    passed=False,
                    score=0.0,
                    notes=f"mc-generic choice '{c.get('key')}' missing choice field",
                ))
                break
        else:
            results.append(DimensionResult(
                name="choice_structure",
                severity="critical",
                passed=True,
                score=10.0,
                notes="All choices have text",
            ))

    # line_reference_bounds: for mc-block/mc-line, check references in bounds
    if q.prompt.typeId in ("mc-block", "mc-line"):
        code_len = len(q.prompt.configuration.code)
        for c in q.prompt.configuration.choices:
            if q.prompt.typeId == "mc-block":
                start, end = c.get("start", 0), c.get("end", 0)
                if start < 0 or end >= code_len or start > end:
                    results.append(DimensionResult(
                        name="line_bounds",
                        severity="critical",
                        passed=False,
                        score=0.0,
                        notes=(
                            f"Choice '{c['key']}' range [{start}-{end}] "
                            f"out of bounds (code has {code_len} lines)"
                        ),
                    ))
                    break
            elif q.prompt.typeId == "mc-line":
                line_num = c.get("choice", 0)
                if line_num < 0 or line_num >= code_len:
                    results.append(DimensionResult(
                        name="line_bounds",
                        severity="critical",
                        passed=False,
                        score=0.0,
                        notes=(
                            f"Choice '{c['key']}' line {line_num} "
                            f"out of bounds (code has {code_len} lines)"
                        ),
                    ))
                    break
        else:
            results.append(DimensionResult(
                name="line_bounds",
                severity="critical",
                passed=True,
                score=10.0,
                notes="All line references within bounds",
            ))

    # roundtrip: question survives export → re-parse
    try:
        from sjqqc.tools import export_platform_json
        exported = export_platform_json(q)
        reparsed = AssessmentQuestion(**json.loads(exported))
        roundtrip_ok = q.to_platform_json() == reparsed.to_platform_json()
    except Exception:
        roundtrip_ok = False
    results.append(DimensionResult(
        name="roundtrip_integrity",
        severity="critical",
        passed=roundtrip_ok,
        score=10.0 if roundtrip_ok else 0.0,
        notes="Export → re-parse identical" if roundtrip_ok else "Round-trip FAILED",
    ))

    return results


def build_score_card(
    q: AssessmentQuestion,
    structural_results: list[DimensionResult],
    llm_results: dict[str, Any] | None = None,
) -> QuestionScoreCard:
    """Build a complete score card from structural + optional LLM results."""
    dimensions = list(structural_results)

    # Add LLM results if available
    if llm_results:
        for dim_name in (
            "technical_accuracy", "stem_clarity", "choice_quality",
            "code_quality", "difficulty_calibration",
        ):
            dim_data = llm_results.get(dim_name, {})
            if isinstance(dim_data, dict):
                score = float(dim_data.get("score", 0))
                dimensions.append(DimensionResult(
                    name=dim_name,
                    severity="major" if score < 5 else "minor",
                    passed=score >= 6,
                    score=score,
                    notes=dim_data.get("notes", ""),
                ))

    # Compute overall
    scores = [d.score for d in dimensions if d.score > 0]
    overall = sum(scores) / len(scores) if scores else 0.0

    critical_fails = [d for d in dimensions if not d.passed and d.severity == "critical"]
    major_fails = [d for d in dimensions if not d.passed and d.severity == "major"]

    if critical_fails:
        verdict = "fail"
    elif major_fails:
        verdict = "needs_revision"
    else:
        verdict = "pass"

    issues = []
    for d in dimensions:
        if not d.passed:
            issues.append(f"[{d.severity.upper()}] {d.name}: {d.notes}")

    return QuestionScoreCard(
        question_id=q.question_id,
        title=q.title,
        type_id=q.prompt.typeId,
        language=q.language,
        path=q.path,
        dimensions=dimensions,
        issues=issues,
        overall_score=round(overall, 1),
        verdict=verdict,
    )


def assess_bank(questions: list[AssessmentQuestion]) -> BankReport:
    """Run structural quality checks on all questions (no LLM needed).

    Returns a BankReport with per-question score cards and aggregate stats.
    For LLM-enhanced assessment, use the reviewer's quality_check() method
    and pass results to build_score_card().
    """
    score_cards: list[QuestionScoreCard] = []

    for q in questions:
        structural = check_structural_quality(q)
        card = build_score_card(q, structural)
        score_cards.append(card)

    report = BankReport(
        total_questions=len(questions),
        score_cards=score_cards,
    )

    logger.info(
        "Bank assessment: {}/{} passing, avg score {:.1f}, weakest: {}",
        report.passing_questions,
        report.total_questions,
        report.average_score,
        report.weakest_dimensions[:3] if report.weakest_dimensions else "none",
    )

    return report
