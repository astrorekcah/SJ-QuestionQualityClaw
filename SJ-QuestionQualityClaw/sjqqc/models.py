"""Domain models for assessment questions, reviews, and feedback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class QuestionState(StrEnum):
    """Lifecycle states for an assessment question."""

    DRAFT = "draft"
    REVIEW = "review"
    REVISION = "revision"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class QuestionType(StrEnum):
    """Supported question formats."""

    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    CODE_REVIEW = "code_review"
    SCENARIO = "scenario"


class Difficulty(StrEnum):
    """Question difficulty tiers."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class ReviewVerdict(StrEnum):
    """Outcome of a quality review."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    FAIL = "fail"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class Choice(BaseModel):
    """A single answer choice for multiple-choice questions."""

    label: str = Field(description="Choice identifier (A, B, C, D, ...)")
    text: str = Field(description="Choice content")
    is_correct: bool = False
    explanation: str | None = Field(
        default=None,
        description="Why this choice is correct or why it's a good distractor",
    )


class Question(BaseModel):
    """An assessment question with metadata."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = Field(description="Short title for the question")
    body: str = Field(description="Full question text / stem")
    question_type: QuestionType = QuestionType.MULTIPLE_CHOICE
    difficulty: Difficulty = Difficulty.INTERMEDIATE
    domain: str = Field(default="general", description="Subject domain (e.g. security, web3)")
    tags: list[str] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
    correct_answer: str | None = Field(
        default=None,
        description="Expected answer for non-MCQ types",
    )
    reference_material: str | None = Field(
        default=None,
        description="Source material or context for the question",
    )
    state: QuestionState = QuestionState.DRAFT
    author: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # External references
    github_pr_url: str | None = None
    linear_ticket_id: str | None = None


class CriterionScore(BaseModel):
    """Score for a single review criterion."""

    criterion: str = Field(description="Name of the quality criterion")
    score: float = Field(ge=0.0, le=10.0, description="Score from 0-10")
    weight: float = Field(default=1.0, ge=0.0, description="Weight for overall scoring")
    feedback: str = Field(description="Specific feedback for this criterion")


class Review(BaseModel):
    """A quality review of an assessment question."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question_id: str = Field(description="ID of the reviewed question")
    verdict: ReviewVerdict
    overall_score: float = Field(ge=0.0, le=10.0)
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    summary: str = Field(description="High-level review summary")
    suggestions: list[str] = Field(
        default_factory=list,
        description="Actionable improvement suggestions",
    )
    revised_body: str | None = Field(
        default=None,
        description="Suggested rewrite of the question body (if applicable)",
    )
    revised_choices: list[Choice] | None = Field(
        default=None,
        description="Suggested rewrite of choices (if applicable)",
    )
    reviewer_model: str = Field(
        default="unknown",
        description="LLM model used for the review",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_llm_response: dict[str, Any] | None = Field(
        default=None,
        description="Full LLM response for audit trail",
    )


class Feedback(BaseModel):
    """Aggregated feedback across multiple reviews of a question."""

    question_id: str
    reviews: list[Review] = Field(default_factory=list)
    average_score: float = 0.0
    consensus_verdict: ReviewVerdict = ReviewVerdict.NEEDS_REVISION
    key_issues: list[str] = Field(default_factory=list)
    revision_count: int = 0
    disputed_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria where reviewer scores diverged by >2 points",
    )

    def compute_consensus(self) -> None:
        """Recompute aggregated metrics from review list."""
        if not self.reviews:
            return
        self.average_score = sum(r.overall_score for r in self.reviews) / len(self.reviews)
        verdicts = [r.verdict for r in self.reviews]
        if all(v == ReviewVerdict.PASS for v in verdicts):
            self.consensus_verdict = ReviewVerdict.PASS
        elif any(v == ReviewVerdict.FAIL for v in verdicts):
            self.consensus_verdict = ReviewVerdict.FAIL
        else:
            self.consensus_verdict = ReviewVerdict.NEEDS_REVISION
        # Collect unique issues
        seen: set[str] = set()
        self.key_issues = []
        for review in self.reviews:
            for suggestion in review.suggestions:
                if suggestion not in seen:
                    self.key_issues.append(suggestion)
                    seen.add(suggestion)
        # Detect disputed criteria (>2 point spread across passes)
        self.disputed_criteria = []
        if len(self.reviews) >= 2:
            criteria_scores: dict[str, list[float]] = {}
            for review in self.reviews:
                for cs in review.criterion_scores:
                    criteria_scores.setdefault(cs.criterion, []).append(cs.score)
            for criterion, scores in criteria_scores.items():
                if max(scores) - min(scores) > 2.0:
                    self.disputed_criteria.append(criterion)


class CriterionDelta(BaseModel):
    """Score change for a single criterion between question versions."""

    criterion: str
    original_score: float
    revised_score: float
    delta: float = Field(description="Positive = improved, negative = regressed")
    note: str = ""


class ComparisonResult(BaseModel):
    """Side-by-side comparison of a question before and after revision."""

    question_id: str
    original_score: float
    revised_score: float
    score_delta: float
    criterion_deltas: list[CriterionDelta] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(
        default_factory=list,
        description="Suggestions from original review not addressed by revision",
    )
    revision_adequate: bool = Field(
        default=False,
        description="True if revision improved score and addressed key feedback",
    )
    original_review: Review | None = None
    revised_review: Review | None = None


class BatchReportEntry(BaseModel):
    """Review result for one question in a batch."""

    question_id: str
    title: str
    domain: str
    verdict: ReviewVerdict
    score: float
    top_issue: str = ""


class BatchReport(BaseModel):
    """Aggregate report for a batch of question reviews."""

    total: int = 0
    passed: int = 0
    needs_revision: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    average_score: float = 0.0
    entries: list[BatchReportEntry] = Field(default_factory=list)
    common_issues: list[str] = Field(
        default_factory=list,
        description="Issues appearing across 2+ questions",
    )
    weakest_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria with lowest average scores across the batch",
    )

    def compute_stats(self) -> None:
        """Recompute aggregate stats from entries."""
        self.total = len(self.entries)
        self.passed = sum(1 for e in self.entries if e.verdict == ReviewVerdict.PASS)
        self.needs_revision = sum(
            1 for e in self.entries if e.verdict == ReviewVerdict.NEEDS_REVISION
        )
        self.failed = sum(1 for e in self.entries if e.verdict == ReviewVerdict.FAIL)
        self.pass_rate = (self.passed / self.total * 100) if self.total else 0.0
        self.average_score = (
            sum(e.score for e in self.entries) / self.total if self.total else 0.0
        )


class RevisionHistoryEntry(BaseModel):
    """A single revision event in a question's history."""

    version: int
    question_snapshot: Question
    review: Review
    comparison: ComparisonResult | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RevisionHistory(BaseModel):
    """Full audit trail of a question's revisions and reviews."""

    question_id: str
    entries: list[RevisionHistoryEntry] = Field(default_factory=list)

    @property
    def current_version(self) -> int:
        return len(self.entries)

    @property
    def latest_review(self) -> Review | None:
        return self.entries[-1].review if self.entries else None

    @property
    def score_trajectory(self) -> list[float]:
        return [e.review.overall_score for e in self.entries]
