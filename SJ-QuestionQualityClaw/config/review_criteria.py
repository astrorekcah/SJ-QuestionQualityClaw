"""Question quality review rubric definitions.

Each criterion has a name, description, weight, and scoring guidance.
The reviewer engine uses these to produce structured, consistent evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Criterion:
    """A single quality criterion with scoring guidance."""

    name: str
    description: str
    weight: float = 1.0
    scoring_guide: str = ""


# ---------------------------------------------------------------------------
# Default rubric — covers the core dimensions of question quality
# ---------------------------------------------------------------------------

CLARITY = Criterion(
    name="clarity",
    description="Is the question stem clear, unambiguous, and grammatically correct?",
    weight=2.0,
    scoring_guide=(
        "10: Crystal clear, no ambiguity. "
        "7: Minor phrasing issues. "
        "4: Confusing but intent discernible. "
        "1: Incomprehensible or fundamentally ambiguous."
    ),
)

CORRECTNESS = Criterion(
    name="correctness",
    description="Is the marked correct answer actually correct? Are all facts accurate?",
    weight=3.0,
    scoring_guide=(
        "10: Correct answer is definitively right, all facts verified. "
        "7: Correct but minor edge cases not addressed. "
        "4: Partially correct or debatable. "
        "1: Marked answer is wrong."
    ),
)

DISTRACTOR_QUALITY = Criterion(
    name="distractor_quality",
    description="Are incorrect choices plausible, non-trivial, and educational?",
    weight=2.0,
    scoring_guide=(
        "10: All distractors are plausible and test real misconceptions. "
        "7: Most distractors are good, one is weak. "
        "4: Obvious answers or 'none of the above' used poorly. "
        "1: Distractors are absurd or all nearly identical."
    ),
)

DIFFICULTY_ALIGNMENT = Criterion(
    name="difficulty_alignment",
    description="Does the actual difficulty match the labeled difficulty tier?",
    weight=1.0,
    scoring_guide=(
        "10: Perfectly calibrated for the stated tier. "
        "7: Slightly easier or harder than labeled. "
        "4: Significantly misaligned. "
        "1: Labeled beginner but requires expert knowledge (or vice versa)."
    ),
)

COVERAGE = Criterion(
    name="coverage",
    description="Does the question effectively test the intended knowledge domain?",
    weight=1.5,
    scoring_guide=(
        "10: Tests a core concept thoroughly. "
        "7: Tests the right area but surface-level. "
        "4: Tangential to the stated domain. "
        "1: Tests something entirely different from the domain tag."
    ),
)

FAIRNESS = Criterion(
    name="fairness",
    description="Is the question free from bias, tricks, and culturally specific assumptions?",
    weight=1.5,
    scoring_guide=(
        "10: Completely fair, no tricks or bias. "
        "7: Minor cultural assumption but still fair. "
        "4: Trick question or relies on obscure trivia. "
        "1: Discriminatory, deceptive, or fundamentally unfair."
    ),
)

ACTIONABILITY = Criterion(
    name="actionability",
    description="Can a learner improve from getting this wrong? Does the question teach?",
    weight=1.0,
    scoring_guide=(
        "10: Getting it wrong reveals a specific knowledge gap with clear fix. "
        "7: Somewhat educational. "
        "4: Memorization-only, no deeper understanding tested. "
        "1: No learning value regardless of outcome."
    ),
)


@dataclass
class ReviewRubric:
    """Complete rubric used by the reviewer engine."""

    criteria: list[Criterion] = field(default_factory=lambda: [
        CLARITY,
        CORRECTNESS,
        DISTRACTOR_QUALITY,
        DIFFICULTY_ALIGNMENT,
        COVERAGE,
        FAIRNESS,
        ACTIONABILITY,
    ])
    pass_threshold: float = 7.0
    revision_threshold: float = 5.0
    # Below revision_threshold → FAIL

    def to_prompt_section(self) -> str:
        """Render the rubric as a text block for LLM prompts."""
        lines = ["Score each criterion from 0-10:\n"]
        for c in self.criteria:
            lines.append(f"**{c.name}** (weight {c.weight}x): {c.description}")
            if c.scoring_guide:
                lines.append(f"  Scoring: {c.scoring_guide}")
            lines.append("")
        lines.append(f"Pass threshold: weighted average >= {self.pass_threshold}")
        lines.append(f"Needs revision: weighted average >= {self.revision_threshold}")
        lines.append(f"Fail: weighted average < {self.revision_threshold}")
        return "\n".join(lines)

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.criteria)


DEFAULT_RUBRIC = ReviewRubric()
