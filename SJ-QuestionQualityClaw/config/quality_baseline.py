"""Quality baseline — the standard every assessment question is measured against.

Each dimension has:
  - A numeric scoring rubric (10/7/4/1) so the LLM knows exactly what each score means
  - Pass threshold (score >= threshold = pass)
  - Severity if failed (critical/major/minor)
  - Concrete fail examples

Used by:
  - quality_check() in reviewer.py — scores questions against these standards
  - validate_feedback() — determines if feedback identifies a real quality gap
  - improve_question() — knows what "better" looks like when generating revisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Quality dimensions with numeric scoring
# ---------------------------------------------------------------------------

class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


@dataclass(frozen=True)
class ScoringLevel:
    """A specific score level with its definition."""

    score: int
    label: str
    description: str


@dataclass(frozen=True)
class QualityDimension:
    """A quality dimension with a numeric scoring rubric."""

    name: str
    description: str
    severity_if_failed: Severity
    pass_threshold: int  # score >= this = pass
    scoring: list[ScoringLevel]  # ordered 10 → 1
    fail_examples: list[str] = field(default_factory=list)

    def scoring_rubric(self) -> str:
        """Render the scoring rubric for LLM prompts."""
        lines = []
        for level in self.scoring:
            lines.append(f"  {level.score}: {level.label} — {level.description}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Universal dimensions (all question types)
# ---------------------------------------------------------------------------

ANSWER_CORRECTNESS = QualityDimension(
    name="answer_correctness",
    description="Is the marked correct answer actually correct?",
    severity_if_failed=Severity.CRITICAL,
    pass_threshold=8,
    scoring=[
        ScoringLevel(10, "Definitively correct",
                     "The answer is objectively right with no edge cases or debate."),
        ScoringLevel(7, "Correct with minor gaps",
                     "The answer is correct but minor edge cases are not addressed."),
        ScoringLevel(4, "Debatable",
                     "The answer is arguably correct but another choice is also defensible."),
        ScoringLevel(1, "Wrong",
                     "The marked answer is factually incorrect."),
    ],
    fail_examples=[
        "Marked answer is factually wrong",
        "Two choices are both correct (ambiguous answer)",
        "Answer key references a choice that doesn't exist",
    ],
)

SINGLE_CORRECT_ANSWER = QualityDimension(
    name="single_correct_answer",
    description="Is there exactly one correct answer with no ambiguity?",
    severity_if_failed=Severity.CRITICAL,
    pass_threshold=8,
    scoring=[
        ScoringLevel(10, "Unambiguous",
                     "Exactly one choice is correct. All others are wrong for specific reasons."),
        ScoringLevel(7, "Mostly clear",
                     "One correct answer, but one distractor is borderline."),
        ScoringLevel(4, "Ambiguous",
                     "Two or more choices could be argued as correct."),
        ScoringLevel(1, "Multiple correct",
                     "Multiple choices are clearly valid answers."),
    ],
    fail_examples=[
        "Choice A and C are both valid approaches",
        "The correct answer depends on interpretation",
    ],
)

STEM_CLARITY = QualityDimension(
    name="stem_clarity",
    description="Does the question stem clearly state what is being asked?",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=6,
    scoring=[
        ScoringLevel(10, "Crystal clear",
                     "The question is immediately understandable. No ambiguity."),
        ScoringLevel(7, "Clear with minor issues",
                     "Understandable but has minor phrasing issues or unnecessary length."),
        ScoringLevel(4, "Confusing",
                     "The intent is discernible but the wording creates confusion."),
        ScoringLevel(1, "Incomprehensible",
                     "Cannot determine what the question is asking."),
    ],
    fail_examples=[
        "Stem says 'identify the issue' without specifying what kind",
        "Scenario so long the actual question gets lost",
    ],
)

SCENARIO_REALISM = QualityDimension(
    name="scenario_realism",
    description="Is the scenario context plausible and relevant?",
    severity_if_failed=Severity.MINOR,
    pass_threshold=5,
    scoring=[
        ScoringLevel(10, "Realistic",
                     "Scenario describes a plausible real-world system and role."),
        ScoringLevel(7, "Mostly realistic",
                     "Minor implausibility but doesn't distract from the question."),
        ScoringLevel(4, "Contrived",
                     "Scenario feels artificial or forced. Distracts from learning."),
        ScoringLevel(1, "Impossible",
                     "Scenario describes a system that couldn't exist."),
    ],
)

DISTRACTOR_PLAUSIBILITY = QualityDimension(
    name="distractor_plausibility",
    description="Are wrong choices plausible enough to test real knowledge?",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=6,
    scoring=[
        ScoringLevel(10, "Excellent distractors",
                     "All wrong choices test real misconceptions."),
        ScoringLevel(7, "Good distractors",
                     "Most distractors are plausible. One may be slightly weak."),
        ScoringLevel(4, "Weak distractors",
                     "Wrong choices are obvious or test the same misconception."),
        ScoringLevel(1, "Trivial",
                     "Wrong choices are absurd. No knowledge needed."),
    ],
    fail_examples=[
        "Wrong choice is obviously unrelated",
        "All distractors test the same misconception",
    ],
)

DOMAIN_ACCURACY = QualityDimension(
    name="domain_accuracy",
    description="Is the technical content accurate for the stated domain?",
    severity_if_failed=Severity.CRITICAL,
    pass_threshold=8,
    scoring=[
        ScoringLevel(10, "Technically impeccable",
                     "All claims, code, and classifications are factually correct."),
        ScoringLevel(7, "Mostly accurate",
                     "Core content is correct but has minor technical imprecision."),
        ScoringLevel(4, "Partially inaccurate",
                     "Contains factual errors that could mislead learners."),
        ScoringLevel(1, "Fundamentally wrong",
                     "Major technical errors. Teaches incorrect concepts."),
    ],
    fail_examples=[
        "Claims a function is vulnerable when it's safe",
        "Misidentifies the CWE category",
        "Uses syntax from a different language",
    ],
)


# ---------------------------------------------------------------------------
# Code-specific dimensions (mc-block, mc-code, mc-line)
# ---------------------------------------------------------------------------

CODE_SYNTACTIC_VALIDITY = QualityDimension(
    name="code_syntactic_validity",
    description="Is the code syntactically valid for the stated language?",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=7,
    scoring=[
        ScoringLevel(10, "Compiles clean",
                     "Code would compile/run without syntax errors given standard libraries."),
        ScoringLevel(7, "Minor issues",
                     "Compiles but has trivial issues (missing import, extra semicolon)."),
        ScoringLevel(4, "Broken syntax",
                     "Visible syntax errors that break compilation."),
        ScoringLevel(1, "Wrong language",
                     "Code uses syntax from a different language entirely."),
    ],
)

CODE_REALISM = QualityDimension(
    name="code_realism",
    description="Does the code represent realistic production patterns?",
    severity_if_failed=Severity.MINOR,
    pass_threshold=5,
    scoring=[
        ScoringLevel(10, "Production-like",
                     "Looks like real code a developer would write in production."),
        ScoringLevel(7, "Plausible",
                     "Reasonable code but somewhat simplified for the exercise."),
        ScoringLevel(4, "Contrived",
                     "Code is clearly written for the exercise, not realistic."),
        ScoringLevel(1, "Toy code",
                     "Variables named foo/bar, unrealistic patterns, mixed frameworks."),
    ],
)

VULNERABILITY_PRESENCE = QualityDimension(
    name="vulnerability_presence",
    description="Does the code contain exactly the vulnerability being tested?",
    severity_if_failed=Severity.CRITICAL,
    pass_threshold=8,
    scoring=[
        ScoringLevel(10, "Clear vulnerability",
                     "The vulnerability is present exactly where the answer points. Unambiguous."),
        ScoringLevel(7, "Present but subtle",
                     "Vulnerability exists but requires careful analysis to confirm location."),
        ScoringLevel(4, "Mislocated",
                     "A vulnerability exists but not at the location the answer indicates."),
        ScoringLevel(1, "Absent",
                     "The described vulnerability does not exist in the code."),
    ],
)


# ---------------------------------------------------------------------------
# Type-specific dimensions
# ---------------------------------------------------------------------------

CHOICE_LINE_ACCURACY = QualityDimension(
    name="choice_line_accuracy",
    description="Do choice line references point to the correct code?",
    severity_if_failed=Severity.CRITICAL,
    pass_threshold=9,
    scoring=[
        ScoringLevel(10, "Exact references",
                     "All line numbers are correct. Ranges contain the relevant code."),
        ScoringLevel(7, "Mostly correct",
                     "References are correct but one range is slightly too wide/narrow."),
        ScoringLevel(4, "Off by significant amount",
                     "Some references point to wrong code sections."),
        ScoringLevel(1, "Out of bounds",
                     "Line numbers are out of range or point to empty/unrelated lines."),
    ],
    fail_examples=[
        "Line number out of bounds",
        "Correct answer points to empty line",
        "Line references shifted after code edit",
    ],
)

CODE_CHOICE_QUALITY = QualityDimension(
    name="code_choice_quality",
    description="Are inline code choice snippets valid and plausible?",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=6,
    scoring=[
        ScoringLevel(10, "All snippets valid",
                     "Every snippet compiles at the insertion point."),
        ScoringLevel(7, "Mostly valid",
                     "Snippets work but one has minor issues (indentation, scope)."),
        ScoringLevel(4, "Broken snippets",
                     "Some snippets won't compile at the insertion point."),
        ScoringLevel(1, "Non-functional",
                     "Snippets are syntactically broken or use wrong variables."),
    ],
)

GENERIC_CHOICE_QUALITY = QualityDimension(
    name="generic_choice_quality",
    description="Are text choices distinct, substantive, and similarly formatted?",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=6,
    scoring=[
        ScoringLevel(10, "Excellent text choices",
                     "Distinct claims, similar length/style."),
        ScoringLevel(7, "Good choices",
                     "Distinct and substantive but format slightly reveals the answer."),
        ScoringLevel(4, "Weak choices",
                     "Obvious differences in length/detail between correct and wrong."),
        ScoringLevel(1, "Trivial choices",
                     "Choices say the same thing or use obvious language."),
    ],
)


# ---------------------------------------------------------------------------
# Quality baseline — assembled per question type
# ---------------------------------------------------------------------------

@dataclass
class QualityBaseline:
    """Complete quality standard for a question type."""

    dimensions: list[QualityDimension]

    @property
    def critical_dimensions(self) -> list[QualityDimension]:
        return [d for d in self.dimensions if d.severity_if_failed == Severity.CRITICAL]

    @property
    def major_dimensions(self) -> list[QualityDimension]:
        return [d for d in self.dimensions if d.severity_if_failed == Severity.MAJOR]

    def to_prompt_section(self) -> str:
        """Render the full baseline with scoring rubrics for LLM prompts."""
        lines = ["## Quality Baseline\n"]
        lines.append("Score each dimension 1-10 using the rubric below.\n")
        for d in self.dimensions:
            lines.append(
                f"### {d.name} [{d.severity_if_failed.upper()}] "
                f"(pass ≥ {d.pass_threshold})"
            )
            lines.append(d.description)
            lines.append("**Scoring rubric**:")
            lines.append(d.scoring_rubric())
            if d.fail_examples:
                lines.append("**Fail examples**: " + "; ".join(d.fail_examples))
            lines.append("")
        return "\n".join(lines)

    @property
    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]

    @property
    def total_weight(self) -> float:
        """Sum of pass thresholds — higher = stricter baseline."""
        return sum(d.pass_threshold for d in self.dimensions)


# Universal
_UNIVERSAL = [
    ANSWER_CORRECTNESS,
    SINGLE_CORRECT_ANSWER,
    STEM_CLARITY,
    SCENARIO_REALISM,
    DISTRACTOR_PLAUSIBILITY,
    DOMAIN_ACCURACY,
]

# Code-specific
_CODE_COMMON = [
    CODE_SYNTACTIC_VALIDITY,
    CODE_REALISM,
    VULNERABILITY_PRESENCE,
]

# Baselines per question type
BASELINE_MC_BLOCK = QualityBaseline(
    dimensions=_UNIVERSAL + _CODE_COMMON + [CHOICE_LINE_ACCURACY],
)

BASELINE_MC_LINE = QualityBaseline(
    dimensions=_UNIVERSAL + _CODE_COMMON + [CHOICE_LINE_ACCURACY],
)

BASELINE_MC_CODE = QualityBaseline(
    dimensions=_UNIVERSAL + _CODE_COMMON + [CODE_CHOICE_QUALITY],
)

BASELINE_MC_GENERIC = QualityBaseline(
    dimensions=_UNIVERSAL + [GENERIC_CHOICE_QUALITY],
)

BASELINES: dict[str, QualityBaseline] = {
    "mc-block": BASELINE_MC_BLOCK,
    "mc-line": BASELINE_MC_LINE,
    "mc-code": BASELINE_MC_CODE,
    "mc-generic": BASELINE_MC_GENERIC,
}


def get_baseline(type_id: str) -> QualityBaseline:
    """Get the quality baseline for a question type."""
    return BASELINES.get(type_id, BASELINE_MC_BLOCK)
