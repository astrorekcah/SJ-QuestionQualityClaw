"""Quality baseline — the standard every assessment question is measured against.

This defines what "quality" means for each question type, language, and domain.
Used by:
  - quality_check() in reviewer.py — scores questions against these standards
  - validate_feedback() — determines if feedback identifies a real quality gap
  - improve_question() — knows what "better" looks like when generating revisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Quality dimensions
# ---------------------------------------------------------------------------

class Severity(StrEnum):
    """How serious a quality issue is."""

    CRITICAL = "critical"      # Must fix — wrong answer, broken code, misleading
    MAJOR = "major"            # Should fix — unclear stem, weak distractors
    MINOR = "minor"            # Nice to fix — style, wording, minor ambiguity
    INFO = "info"              # Observation — not necessarily a problem


@dataclass(frozen=True)
class QualityDimension:
    """A single quality dimension with pass/fail criteria."""

    name: str
    description: str
    severity_if_failed: Severity
    pass_criteria: str
    fail_examples: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Universal dimensions (apply to ALL question types)
# ---------------------------------------------------------------------------

ANSWER_CORRECTNESS = QualityDimension(
    name="answer_correctness",
    description="The marked correct answer must be definitively correct.",
    severity_if_failed=Severity.CRITICAL,
    pass_criteria=(
        "Exactly one choice is correct. The correct answer key matches "
        "the objectively right answer. No other choice is also defensibly correct."
    ),
    fail_examples=[
        "Marked answer is factually wrong",
        "Two choices are both correct (ambiguous answer)",
        "Answer key references a choice that doesn't exist",
    ],
)

SINGLE_CORRECT_ANSWER = QualityDimension(
    name="single_correct_answer",
    description="Exactly one choice must be the correct answer — no ambiguity.",
    severity_if_failed=Severity.CRITICAL,
    pass_criteria=(
        "Only one choice is correct. All other choices are clearly wrong "
        "for specific, articulable reasons. No 'it depends' situations."
    ),
    fail_examples=[
        "Choice A and C are both valid approaches",
        "The correct answer depends on interpretation of the scenario",
        "Multiple choices point to the same vulnerability",
    ],
)

STEM_CLARITY = QualityDimension(
    name="stem_clarity",
    description="The question stem must clearly state what is being asked.",
    severity_if_failed=Severity.MAJOR,
    pass_criteria=(
        "The stem contains a clear question or directive. The reader knows "
        "exactly what they're looking for (a vulnerability, a fix, a correct "
        "implementation). No ambiguous pronouns or vague references."
    ),
    fail_examples=[
        "Stem says 'identify the issue' but doesn't specify what kind",
        "Scenario is so long the actual question gets lost",
        "Uses 'it' or 'this' without clear antecedent",
    ],
)

SCENARIO_REALISM = QualityDimension(
    name="scenario_realism",
    description="The scenario context must be plausible and relevant.",
    severity_if_failed=Severity.MINOR,
    pass_criteria=(
        "The scenario describes a realistic system, role, and context. "
        "The company/role framing helps the reader understand the stakes "
        "without being distracting or contrived."
    ),
    fail_examples=[
        "Scenario describes impossible system architecture",
        "Role doesn't match the task (intern doing CISO work)",
        "Company details are irrelevant padding",
    ],
)

DISTRACTOR_PLAUSIBILITY = QualityDimension(
    name="distractor_plausibility",
    description="Wrong choices must be plausible enough to test real knowledge.",
    severity_if_failed=Severity.MAJOR,
    pass_criteria=(
        "Each distractor is wrong for a specific, articulable reason but "
        "looks plausible to someone who doesn't fully understand the concept. "
        "Distractors test real misconceptions, not random content."
    ),
    fail_examples=[
        "Wrong choice is obviously unrelated to the question",
        "All distractors test the same misconception",
        "Wrong choice is so similar to correct that it's unfair",
    ],
)

DOMAIN_ACCURACY = QualityDimension(
    name="domain_accuracy",
    description="Technical content must be accurate for the stated domain.",
    severity_if_failed=Severity.CRITICAL,
    pass_criteria=(
        "All technical claims in the stem, code, and choices are factually "
        "correct for the stated programming language and security domain. "
        "Vulnerability classifications match industry standards (CWE, OWASP)."
    ),
    fail_examples=[
        "Claims a function is vulnerable when it's actually safe",
        "Misidentifies the CWE category",
        "Uses syntax from a different language",
    ],
)


# ---------------------------------------------------------------------------
# Code-specific dimensions (mc-block, mc-code, mc-line)
# ---------------------------------------------------------------------------

CODE_SYNTACTIC_VALIDITY = QualityDimension(
    name="code_syntactic_validity",
    description="Code must be syntactically valid for the stated language.",
    severity_if_failed=Severity.MAJOR,
    pass_criteria=(
        "The code compiles/runs (or would, given standard libraries). "
        "No syntax errors, missing brackets, wrong keywords. "
        "Import statements reference real packages."
    ),
    fail_examples=[
        "Missing closing bracket",
        "Python code uses Ruby syntax",
        "Import references nonexistent package",
    ],
)

CODE_REALISM = QualityDimension(
    name="code_realism",
    description="Code must represent realistic production patterns.",
    severity_if_failed=Severity.MINOR,
    pass_criteria=(
        "The code looks like something a developer would actually write. "
        "Uses realistic variable names, follows common patterns for the "
        "language/framework, and represents a believable system component."
    ),
    fail_examples=[
        "Variable names like 'foo', 'bar', 'test123'",
        "Security code that no real developer would write",
        "Mixing multiple frameworks that wouldn't be used together",
    ],
)

VULNERABILITY_PRESENCE = QualityDimension(
    name="vulnerability_presence",
    description="The code must contain exactly the vulnerability being tested.",
    severity_if_failed=Severity.CRITICAL,
    pass_criteria=(
        "The vulnerability described in the stem is actually present in "
        "the code. It's in exactly the location the correct answer points to. "
        "The vulnerability is not an artifact of simplified example code."
    ),
    fail_examples=[
        "Stem says 'SQL injection' but code uses parameterized queries",
        "Vulnerability is in a different location than the correct answer",
        "Code is so simplified the vulnerability is artificial",
    ],
)


# ---------------------------------------------------------------------------
# Type-specific dimensions
# ---------------------------------------------------------------------------

CHOICE_LINE_ACCURACY = QualityDimension(
    name="choice_line_accuracy",
    description="For mc-block/mc-line: choice line references must be correct.",
    severity_if_failed=Severity.CRITICAL,
    pass_criteria=(
        "Line numbers in choices point to actual code lines within bounds. "
        "For mc-block: start <= end, range contains meaningful code. "
        "For mc-line: line contains the relevant code (not empty/whitespace). "
        "The correct answer points to the actual vulnerable code."
    ),
    fail_examples=[
        "Line number out of bounds",
        "Correct answer points to empty line or comment",
        "Block range includes unrelated code",
        "Line references shifted after code edit but not updated",
    ],
)

CODE_CHOICE_QUALITY = QualityDimension(
    name="code_choice_quality",
    description="For mc-code: inline code snippets must be syntactically valid.",
    severity_if_failed=Severity.MAJOR,
    pass_criteria=(
        "Each code choice snippet is syntactically valid, fits the insertion "
        "point (codeLine), and represents a plausible implementation. "
        "The correct choice fixes/demonstrates the security concept."
    ),
    fail_examples=[
        "Code snippet won't compile at the insertion point",
        "Indentation is wrong for the surrounding context",
        "Snippet uses variables not in scope",
    ],
)

GENERIC_CHOICE_QUALITY = QualityDimension(
    name="generic_choice_quality",
    description="For mc-generic: text choices must be distinct and substantive.",
    severity_if_failed=Severity.MAJOR,
    pass_criteria=(
        "Each text choice makes a clear, distinct claim. Choices are "
        "similar enough in length/style that format doesn't reveal the answer. "
        "Wrong choices represent real misconceptions about the topic."
    ),
    fail_examples=[
        "Correct answer is much longer/more detailed than distractors",
        "Choices use 'always/never' language that makes them obviously wrong",
        "Two choices say essentially the same thing",
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
        """Render as text for LLM system prompts."""
        lines = ["## Quality Baseline\n"]
        for d in self.dimensions:
            lines.append(
                f"### {d.name} [{d.severity_if_failed.upper()}]"
            )
            lines.append(d.description)
            lines.append(f"**Pass criteria**: {d.pass_criteria}")
            if d.fail_examples:
                lines.append("**Fail examples**:")
                for ex in d.fail_examples:
                    lines.append(f"  - {ex}")
            lines.append("")
        return "\n".join(lines)

    @property
    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]


# Universal dimensions for all types
_UNIVERSAL = [
    ANSWER_CORRECTNESS,
    SINGLE_CORRECT_ANSWER,
    STEM_CLARITY,
    SCENARIO_REALISM,
    DISTRACTOR_PLAUSIBILITY,
    DOMAIN_ACCURACY,
]

# Code-specific (shared by mc-block, mc-code, mc-line)
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

# Lookup by typeId
BASELINES: dict[str, QualityBaseline] = {
    "mc-block": BASELINE_MC_BLOCK,
    "mc-line": BASELINE_MC_LINE,
    "mc-code": BASELINE_MC_CODE,
    "mc-generic": BASELINE_MC_GENERIC,
}


def get_baseline(type_id: str) -> QualityBaseline:
    """Get the quality baseline for a question type."""
    return BASELINES.get(type_id, BASELINE_MC_BLOCK)
