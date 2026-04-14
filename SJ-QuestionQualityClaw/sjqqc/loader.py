"""Question + feedback file loader.

Loads questions and their paired feedback from the filesystem.
Supports two feedback file conventions:

1. Same name with .feedback.json suffix:
   questions/ruby_auth.json → questions/ruby_auth.feedback.json

2. Same name with .feedback.txt suffix (plain text):
   questions/ruby_auth.json → questions/ruby_auth.feedback.txt

Feedback JSON format:
{
  "comment": "The answer should be D, not C",
  "author": "reviewer-name",
  "target_choice": "c",          // optional
  "target_lines": [66, 70]       // optional
}

Feedback TXT format:
Just the comment text, one feedback per file.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from sjqqc.models import AssessmentQuestion, FeedbackComment


def load_question(path: Path | str) -> AssessmentQuestion:
    """Load a single question from a JSON file."""
    path = Path(path)
    return AssessmentQuestion(**json.loads(path.read_text()))


def find_feedback_file(question_path: Path | str) -> Path | None:
    """Find the feedback file paired with a question file.

    Looks for:
      <name>.feedback.json
      <name>.feedback.txt
    """
    qp = Path(question_path)
    stem = qp.stem

    # Try .feedback.json first
    fb_json = qp.parent / f"{stem}.feedback.json"
    if fb_json.exists():
        return fb_json

    # Try .feedback.txt
    fb_txt = qp.parent / f"{stem}.feedback.txt"
    if fb_txt.exists():
        return fb_txt

    return None


def load_feedback(
    feedback_path: Path | str,
    question_path: str,
) -> FeedbackComment:
    """Load feedback from a .feedback.json or .feedback.txt file."""
    fp = Path(feedback_path)
    text = fp.read_text().strip()

    if fp.suffix == ".json":
        data = json.loads(text)
        return FeedbackComment(
            question_path=question_path,
            comment=data.get("comment", ""),
            author=data.get("author", "reviewer"),
            target_choice=data.get("target_choice"),
            target_lines=tuple(data["target_lines"])
            if data.get("target_lines")
            else None,
        )
    else:
        # Plain text — entire file is the comment
        return FeedbackComment(
            question_path=question_path,
            comment=text,
        )


def load_question_with_feedback(
    question_path: Path | str,
) -> tuple[AssessmentQuestion, FeedbackComment | None]:
    """Load a question and its paired feedback (if any).

    Returns (question, feedback_or_None).
    """
    qp = Path(question_path)
    question = load_question(qp)

    fb_path = find_feedback_file(qp)
    if fb_path:
        feedback = load_feedback(fb_path, question.path)
        logger.info(
            "Loaded feedback for {}: '{}'",
            question.question_id,
            feedback.comment[:60],
        )
        return question, feedback

    return question, None


def load_all_with_feedback(
    directory: Path | str,
) -> list[tuple[AssessmentQuestion, FeedbackComment | None]]:
    """Load all questions in a directory with their paired feedback.

    Skips _revised.json files. Returns list of (question, feedback_or_None).
    """
    d = Path(directory)
    results: list[tuple[AssessmentQuestion, FeedbackComment | None]] = []

    for f in sorted(d.glob("*.json")):
        if f.name.endswith(("_revised.json", "_exported.json", ".feedback.json")):
            continue
        try:
            q, fb = load_question_with_feedback(f)
            results.append((q, fb))
        except Exception as exc:
            logger.warning("Failed to load {}: {}", f.name, exc)

    with_fb = sum(1 for _, fb in results if fb is not None)
    logger.info(
        "Loaded {} questions ({} with feedback) from {}",
        len(results), with_fb, d,
    )
    return results
