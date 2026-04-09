"""Tool functions that IronClaw skills call into.

Skills decide WHAT to change. These tools DO the work:
- Apply a specific change to a question
- Return a FieldChange record for the changelog
- Validate structural integrity after each step

Every tool takes the current question state, applies one change,
and returns (updated_question, field_change_record).
"""

from __future__ import annotations

import json
from copy import deepcopy

from loguru import logger

from sjqqc.models import (
    Answer,
    AssessmentQuestion,
    FieldChange,
    PromptType,
    StepValidation,
)

# ---------------------------------------------------------------------------
# Core mutation tools
# ---------------------------------------------------------------------------

def update_answer(
    question: AssessmentQuestion,
    new_answer_key: str,
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, FieldChange]:
    """Change the correct answer to a different choice key."""
    q = question.model_copy(deep=True)
    old_key = q.correct_answer_key

    if new_answer_key not in q.choice_keys():
        raise ValueError(
            f"Answer key '{new_answer_key}' not in choices: {q.choice_keys()}"
        )

    q.answers = [Answer(value=new_answer_key)]

    change = FieldChange(
        field_path="answers[0].value",
        old_value=old_key,
        new_value=new_answer_key,
        reason=reason or f"Changed correct answer from {old_key} to {new_answer_key}",
        strategy=strategy,
    )
    logger.info("Tool: update_answer {} → {}", old_key, new_answer_key)
    return q, change


def update_stem(
    question: AssessmentQuestion,
    new_stem: str,
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, FieldChange]:
    """Replace the question stem text."""
    q = question.model_copy(deep=True)
    old_stem = q.prompt.configuration.prompt

    q.prompt.configuration.prompt = new_stem

    change = FieldChange(
        field_path="prompt.configuration.prompt",
        old_value=old_stem,
        new_value=new_stem,
        reason=reason or "Updated question stem",
        strategy=strategy,
    )
    logger.info("Tool: update_stem ({} → {} chars)", len(old_stem), len(new_stem))
    return q, change


def update_code(
    question: AssessmentQuestion,
    line_idx: int,
    new_line: str,
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, FieldChange]:
    """Replace a single code line."""
    q = question.model_copy(deep=True)
    code = q.prompt.configuration.code

    if line_idx < 0 or line_idx >= len(code):
        raise ValueError(f"Line index {line_idx} out of range (0-{len(code) - 1})")

    old_line = code[line_idx]
    code[line_idx] = new_line

    change = FieldChange(
        field_path=f"prompt.configuration.code[{line_idx}]",
        old_value=old_line,
        new_value=new_line,
        reason=reason or f"Updated code line {line_idx}",
        strategy=strategy,
    )
    logger.info("Tool: update_code line {}", line_idx)
    return q, change


def update_code_block(
    question: AssessmentQuestion,
    start: int,
    end: int,
    new_lines: list[str],
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, list[FieldChange]]:
    """Replace a range of code lines. Preserves line count if len(new_lines) == end-start+1."""
    q = question.model_copy(deep=True)
    code = q.prompt.configuration.code

    if start < 0 or end >= len(code) or start > end:
        raise ValueError(f"Invalid range [{start}, {end}] for code with {len(code)} lines")

    old_lines = code[start:end + 1]
    changes: list[FieldChange] = []

    # Replace line by line for precise tracking
    if len(new_lines) == len(old_lines):
        for i, (old, new) in enumerate(zip(old_lines, new_lines, strict=True)):
            if old != new:
                code[start + i] = new
                changes.append(FieldChange(
                    field_path=f"prompt.configuration.code[{start + i}]",
                    old_value=old,
                    new_value=new,
                    reason=reason or f"Updated code line {start + i}",
                    strategy=strategy,
                ))
    else:
        # Different line count — replace entire block
        q.prompt.configuration.code = code[:start] + new_lines + code[end + 1:]
        changes.append(FieldChange(
            field_path=f"prompt.configuration.code[{start}:{end + 1}]",
            old_value=old_lines,
            new_value=new_lines,
            reason=reason or f"Replaced code block lines {start}-{end}",
            strategy=strategy,
        ))

    logger.info("Tool: update_code_block [{}-{}], {} changes", start, end, len(changes))
    return q, changes


def update_choice(
    question: AssessmentQuestion,
    choice_key: str,
    new_content: dict,
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, FieldChange]:
    """Update a choice's content while preserving its key and structure type."""
    q = question.model_copy(deep=True)
    choices = q.prompt.configuration.choices

    idx = None
    old_choice = None
    for i, c in enumerate(choices):
        if c.get("key") == choice_key:
            idx = i
            old_choice = deepcopy(c)
            break

    if idx is None:
        raise ValueError(f"Choice key '{choice_key}' not found")

    # Merge: keep key, update content fields
    updated = {"key": choice_key, **new_content}

    # Validate structure matches typeId
    _validate_choice_structure(q.prompt_type, updated)

    choices[idx] = updated

    change = FieldChange(
        field_path=f"prompt.configuration.choices[{idx}]",
        old_value=old_choice,
        new_value=updated,
        reason=reason or f"Updated choice {choice_key}",
        strategy=strategy,
    )
    logger.info("Tool: update_choice key={}", choice_key)
    return q, change


def reindex_choices(
    question: AssessmentQuestion,
    line_delta: int,
    *,
    reason: str = "",
    strategy: str = "",
) -> tuple[AssessmentQuestion, list[FieldChange]]:
    """Shift line references in choices by a delta (after code insertion/deletion).

    Only applies to mc-block (start/end) and mc-line (choice) types.
    """
    q = question.model_copy(deep=True)
    changes: list[FieldChange] = []

    if q.prompt_type == PromptType.MC_BLOCK:
        for i, c in enumerate(q.prompt.configuration.choices):
            old_start, old_end = c["start"], c["end"]
            c["start"] = old_start + line_delta
            c["end"] = old_end + line_delta
            changes.append(FieldChange(
                field_path=f"prompt.configuration.choices[{i}]",
                old_value={"start": old_start, "end": old_end},
                new_value={"start": c["start"], "end": c["end"]},
                reason=reason or f"Reindexed choice {c['key']} by {line_delta:+d}",
                strategy=strategy,
            ))
    elif q.prompt_type == PromptType.MC_LINE:
        for i, c in enumerate(q.prompt.configuration.choices):
            old_line = c["choice"]
            c["choice"] = old_line + line_delta
            changes.append(FieldChange(
                field_path=f"prompt.configuration.choices[{i}]",
                old_value={"choice": old_line},
                new_value={"choice": c["choice"]},
                reason=reason or f"Reindexed choice {c['key']} by {line_delta:+d}",
                strategy=strategy,
            ))

    logger.info(
        "Tool: reindex_choices delta={:+d}, {} changes", line_delta, len(changes)
    )
    return q, changes


# ---------------------------------------------------------------------------
# Validation tools
# ---------------------------------------------------------------------------

def validate_step(
    original: AssessmentQuestion,
    current: AssessmentQuestion,
) -> StepValidation:
    """Validate that a question is still structurally valid after a change."""
    errors: list[str] = []
    warnings: list[str] = []

    # typeId must not change
    if current.prompt.typeId != original.prompt.typeId:
        errors.append(
            f"typeId changed: {original.prompt.typeId} → {current.prompt.typeId}"
        )

    # Choice keys must match
    if current.choice_keys() != original.choice_keys():
        errors.append(
            f"Choice keys changed: {original.choice_keys()} → {current.choice_keys()}"
        )

    # Must have answers
    if not current.answers:
        errors.append("answers array is empty")

    # Answer must reference a valid choice
    if current.correct_answer_key and current.correct_answer_key not in current.choice_keys():
        errors.append(
            f"Answer '{current.correct_answer_key}' not in choices {current.choice_keys()}"
        )

    # Code must be non-empty (except mc-generic which has no code)
    if not current.prompt.configuration.code and current.prompt.typeId != "mc-generic":
        errors.append("code array is empty")

    # Choice structure per typeId
    for c in current.prompt.configuration.choices:
        try:
            _validate_choice_structure(current.prompt_type, c)
        except ValueError as e:
            errors.append(str(e))

    # Code line count change is a warning, not error
    orig_lines = len(original.prompt.configuration.code)
    curr_lines = len(current.prompt.configuration.code)
    if orig_lines != curr_lines:
        warnings.append(
            f"Code line count changed: {orig_lines} → {curr_lines}"
        )

    # Path must not change
    if current.path != original.path:
        errors.append(f"path changed: {original.path} → {current.path}")

    return StepValidation(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_roundtrip(
    original: AssessmentQuestion,
    revised: AssessmentQuestion,
) -> bool:
    """Export revised to platform JSON, re-parse, and verify structural integrity.

    Raises ValueError on failure.
    """
    exported = revised.to_platform_json()
    try:
        reparsed = AssessmentQuestion(**exported)
    except Exception as exc:
        raise ValueError(f"Round-trip parse failed: {exc}") from exc

    step_val = validate_step(original, reparsed)
    if not step_val.passed:
        raise ValueError(
            "Round-trip validation failed:\n"
            + "\n".join(f"  - {e}" for e in step_val.errors)
        )
    return True


# ---------------------------------------------------------------------------
# Export tools
# ---------------------------------------------------------------------------

def export_platform_json(question: AssessmentQuestion) -> str:
    """Export question as platform-ready JSON string."""
    return json.dumps(question.to_platform_json(), indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_choice_structure(prompt_type: PromptType, choice: dict) -> None:
    """Verify a choice dict has the required fields for its typeId."""
    key = choice.get("key", "?")
    if prompt_type == PromptType.MC_BLOCK:
        if "start" not in choice or "end" not in choice:
            raise ValueError(f"mc-block choice '{key}' missing start/end")
    elif prompt_type == PromptType.MC_LINE:
        if "choice" not in choice:
            raise ValueError(f"mc-line choice '{key}' missing choice field")
    elif prompt_type == PromptType.MC_CODE and "code" not in choice:
        raise ValueError(f"mc-code choice '{key}' missing code field")
    elif prompt_type == PromptType.MC_GENERIC and "choice" not in choice:
        raise ValueError(f"mc-generic choice '{key}' missing choice field")
