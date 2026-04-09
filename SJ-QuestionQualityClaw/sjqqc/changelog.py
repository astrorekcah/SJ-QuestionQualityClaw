"""Field-level diff engine for question improvement changelogs."""

from __future__ import annotations

from sjqqc.models import (
    AssessmentQuestion,
    FieldChange,
    ImprovementChangelog,
    ImprovementStep,
)


def diff_fields(
    original: AssessmentQuestion,
    revised: AssessmentQuestion,
) -> list[FieldChange]:
    """Compute field-level diffs between original and revised question.

    Returns a list of FieldChange records for every field that differs.
    """
    changes: list[FieldChange] = []

    # Stem
    if original.stem != revised.stem:
        changes.append(FieldChange(
            field_path="prompt.configuration.prompt",
            old_value=original.stem,
            new_value=revised.stem,
        ))

    # Code (line by line)
    orig_code = original.prompt.configuration.code
    rev_code = revised.prompt.configuration.code
    max_lines = max(len(orig_code), len(rev_code))
    for i in range(max_lines):
        old_line = orig_code[i] if i < len(orig_code) else None
        new_line = rev_code[i] if i < len(rev_code) else None
        if old_line != new_line:
            changes.append(FieldChange(
                field_path=f"prompt.configuration.code[{i}]",
                old_value=old_line,
                new_value=new_line,
            ))

    # Choices
    orig_choices = original.prompt.configuration.choices
    rev_choices = revised.prompt.configuration.choices
    for i in range(max(len(orig_choices), len(rev_choices))):
        old_c = orig_choices[i] if i < len(orig_choices) else None
        new_c = rev_choices[i] if i < len(rev_choices) else None
        if old_c != new_c:
            key = (new_c or old_c or {}).get("key", str(i))
            changes.append(FieldChange(
                field_path=f"prompt.configuration.choices[{i}]",
                old_value=old_c,
                new_value=new_c,
                reason=f"Choice {key} changed",
            ))

    # Answers
    orig_answers = [a.value for a in original.answers]
    rev_answers = [a.value for a in revised.answers]
    if orig_answers != rev_answers:
        changes.append(FieldChange(
            field_path="answers",
            old_value=orig_answers,
            new_value=rev_answers,
        ))

    # Title
    if original.title != revised.title:
        changes.append(FieldChange(
            field_path="title",
            old_value=original.title,
            new_value=revised.title,
        ))

    # codeLine (mc-code)
    orig_cl = original.prompt.configuration.codeLine
    rev_cl = revised.prompt.configuration.codeLine
    if orig_cl != rev_cl:
        changes.append(FieldChange(
            field_path="prompt.configuration.codeLine",
            old_value=orig_cl,
            new_value=rev_cl,
        ))

    return changes


def build_changelog(
    original: AssessmentQuestion,
    revised: AssessmentQuestion,
    steps: list[ImprovementStep] | None = None,
    *,
    feedback_id: str = "",
) -> ImprovementChangelog:
    """Build a complete changelog from original/revised + optional pipeline steps.

    If steps are provided (from the pipeline), uses those.
    Otherwise, computes field diffs directly.
    """
    if steps:
        changelog = ImprovementChangelog(
            question_path=original.path,
            feedback_id=feedback_id,
            steps=steps,
        )
    else:
        # No pipeline steps — compute diff and wrap in a single step
        field_changes = diff_fields(original, revised)
        step = ImprovementStep(
            strategy="direct_revision",
            fields_changed=field_changes,
            notes="Changes computed by field diff (no pipeline steps)",
        )
        changelog = ImprovementChangelog(
            question_path=original.path,
            feedback_id=feedback_id,
            steps=[step],
        )

    return changelog
