"""Domain models — matches the actual platform question schema + feedback workflow.

Platform question types:
  mc-block: select a block of code (choices reference line ranges)
  mc-code:  select a code snippet (choices contain inline code)
  mc-line:  select a single line (choices reference line numbers)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PromptType(StrEnum):
    """Platform question prompt types."""

    MC_BLOCK = "mc-block"
    MC_CODE = "mc-code"
    MC_LINE = "mc-line"


class FeedbackVerdict(StrEnum):
    """Result of validating a human feedback comment."""

    VALID = "valid"
    PARTIALLY_VALID = "partially_valid"
    INVALID = "invalid"
    UNCLEAR = "unclear"


class QuestionState(StrEnum):
    """Lifecycle states for an assessment question."""

    ACTIVE = "active"
    FEEDBACK_RECEIVED = "feedback_received"
    UNDER_REVIEW = "under_review"
    REVISION = "revision"
    UPDATED = "updated"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Platform question schema (matches real JSON files exactly)
# ---------------------------------------------------------------------------

class BlockChoice(BaseModel):
    """Choice for mc-block: references a range of code lines."""

    key: str
    start: int
    end: int


class CodeChoice(BaseModel):
    """Choice for mc-code: contains inline code snippet."""

    key: str
    code: list[str]


class LineChoice(BaseModel):
    """Choice for mc-line: references a single line number."""

    key: str
    choice: int


class PromptConfiguration(BaseModel):
    """The prompt configuration — flexible to handle all question types."""

    prompt: str = Field(description="The question stem / scenario text")
    code: list[str] = Field(default_factory=list, description="Code lines")
    choices: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw choices — shape varies by typeId",
    )
    # mc-code specific: which line to insert the code choice at
    codeLine: int | None = Field(default=None, alias="codeLine")  # noqa: N815

    model_config = {"populate_by_name": True}


class Prompt(BaseModel):
    """The prompt section of a platform question."""

    typeId: str = Field(description="mc-block | mc-code | mc-line")  # noqa: N815
    configuration: PromptConfiguration


class Answer(BaseModel):
    """A correct answer reference."""

    value: str


class AssessmentQuestion(BaseModel):
    """A platform assessment question — matches the real JSON schema exactly.

    This is the primary data model. All questions are loaded, stored,
    and exported in this format.
    """

    path: str = Field(description="Categorization path in the question bank")
    title: str = Field(description="Display title")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata (e.g. programmingLanguage)",
    )
    prompt: Prompt
    answers: list[Answer] = Field(default_factory=list)

    # --- Derived helpers (not in platform JSON) ---
    state: QuestionState = QuestionState.ACTIVE
    linear_ticket_id: str | None = None
    github_pr_url: str | None = None

    @property
    def question_id(self) -> str:
        """Stable ID derived from the path."""
        return self.path.rsplit("/", 1)[-1] if "/" in self.path else self.path

    @property
    def prompt_type(self) -> PromptType:
        return PromptType(self.prompt.typeId)

    @property
    def language(self) -> str:
        langs = self.parameters.get("programmingLanguage", [])
        return langs[0] if langs else "unknown"

    @property
    def correct_answer_key(self) -> str | None:
        return self.answers[0].value if self.answers else None

    @property
    def code_text(self) -> str:
        """Join code lines into a single string for LLM context."""
        return "\n".join(self.prompt.configuration.code)

    @property
    def stem(self) -> str:
        return self.prompt.configuration.prompt

    def choice_keys(self) -> list[str]:
        return [c["key"] for c in self.prompt.configuration.choices]

    def describe_choice(self, key: str) -> str:
        """Human-readable description of what a choice points to."""
        for c in self.prompt.configuration.choices:
            if c.get("key") != key:
                continue
            if self.prompt_type == PromptType.MC_BLOCK:
                start, end = c["start"], c["end"]
                lines = self.prompt.configuration.code[start:end + 1]
                return f"Lines {start}-{end}:\n" + "\n".join(lines)
            elif self.prompt_type == PromptType.MC_LINE:
                line_num = c["choice"]
                line = self.prompt.configuration.code[line_num]
                return f"Line {line_num}: {line}"
            elif self.prompt_type == PromptType.MC_CODE:
                return "\n".join(c.get("code", []))
        return f"Choice {key} (not found)"

    def to_platform_json(self) -> dict[str, Any]:
        """Export back to the platform JSON format (no internal fields)."""
        return self.model_dump(
            include={"path", "title", "parameters", "prompt", "answers"},
            by_alias=True,
        )


# ---------------------------------------------------------------------------
# Feedback workflow models
# ---------------------------------------------------------------------------

class FeedbackComment(BaseModel):
    """A human feedback comment on a question.

    This is the input trigger for the whole system — someone leaves a
    comment saying "the correct answer is wrong" or "choice B is
    also correct" or "the scenario is unrealistic".
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question_path: str = Field(description="Path of the question being commented on")
    author: str = Field(default="reviewer")
    comment: str = Field(description="The raw feedback text")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Optional: which specific choice or line the comment refers to
    target_choice: str | None = None
    target_lines: tuple[int, int] | None = None


class FeedbackValidation(BaseModel):
    """Result of LLM-validating a human feedback comment.

    The system analyzes whether the feedback is technically correct
    before applying any changes.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    feedback_id: str
    question_path: str
    verdict: FeedbackVerdict
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How confident the LLM is in its assessment",
    )
    reasoning: str = Field(description="Detailed analysis of why the feedback is/isn't valid")
    affected_areas: list[str] = Field(
        default_factory=list,
        description="What parts of the question are affected (stem, choices, answer, code)",
    )
    requires_human_review: bool = Field(
        default=False,
        description="True if the LLM can't determine validity with high confidence",
    )
    suggested_action: str = Field(
        default="",
        description="What to do: 'update_answer', 'revise_stem', 'revise_choices', etc.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_llm_response: dict[str, Any] | None = None


class QuestionRevision(BaseModel):
    """A revised version of a question produced by the system."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question_path: str
    feedback_id: str
    validation_id: str
    original: AssessmentQuestion
    revised: AssessmentQuestion
    changes_made: list[str] = Field(
        default_factory=list,
        description="Description of each change",
    )
    rationale: str = Field(
        default="",
        description="Why these changes address the feedback",
    )
    changelog: ImprovementChangelog | None = Field(
        default=None,
        description="Field-level changelog from the pipeline",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Pipeline changelog models
# ---------------------------------------------------------------------------

class FieldChange(BaseModel):
    """A single field-level change made during improvement."""

    field_path: str = Field(description="e.g. prompt.configuration.code[42]")
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    strategy: str = Field(default="", description="Which skill made this change")
    validated: bool = False


class StepValidation(BaseModel):
    """Result of validating a single improvement step."""

    passed: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImprovementStep(BaseModel):
    """One step in the improvement pipeline."""

    strategy: str = Field(description="Skill name (e.g. fix_answer, fix_code)")
    fields_changed: list[FieldChange] = Field(default_factory=list)
    validation: StepValidation = Field(default_factory=StepValidation)
    notes: str = ""


class ImprovementChangelog(BaseModel):
    """Full changelog for a question improvement run."""

    question_path: str
    feedback_id: str = ""
    steps: list[ImprovementStep] = Field(default_factory=list)

    @property
    def field_changes(self) -> list[FieldChange]:
        """All field changes flattened from all steps."""
        return [fc for step in self.steps for fc in step.fields_changed]

    @property
    def total_fields_changed(self) -> int:
        return len(self.field_changes)

    @property
    def all_steps_valid(self) -> bool:
        return all(s.validation.passed for s in self.steps)

    @property
    def summary(self) -> dict[str, bool]:
        paths = {fc.field_path for fc in self.field_changes}
        return {
            "answer_changed": any("answers" in p for p in paths),
            "code_changed": any("code" in p for p in paths),
            "choices_changed": any("choices" in p for p in paths),
            "stem_changed": any("prompt" in p and "code" not in p for p in paths),
        }

    @property
    def strategies_used(self) -> list[str]:
        return [s.strategy for s in self.steps]


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class ReviewEvent(BaseModel):
    """A single event in the audit trail for a question."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = Field(
        description="feedback_received | validation_complete | revision_created | "
        "human_review_requested | question_updated | question_rejected"
    )
    feedback_id: str | None = None
    validation_id: str | None = None
    revision_id: str | None = None
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class QuestionAuditTrail(BaseModel):
    """Full history of feedback and revisions for a question."""

    question_path: str
    events: list[ReviewEvent] = Field(default_factory=list)

    @property
    def feedback_count(self) -> int:
        return sum(1 for e in self.events if e.event_type == "feedback_received")

    @property
    def revision_count(self) -> int:
        return sum(1 for e in self.events if e.event_type == "revision_created")

    @property
    def latest_event(self) -> ReviewEvent | None:
        return self.events[-1] if self.events else None
