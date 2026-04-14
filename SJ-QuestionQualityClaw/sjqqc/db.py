"""Thin database persistence layer.

Provides async functions to persist audit trail events, feedback,
and revisions to PostgreSQL. Falls back gracefully when the database
is unavailable.

Uses psycopg (async) directly — no ORM overhead.
"""

from __future__ import annotations

import json
import os

from loguru import logger

from sjqqc.models import (
    FeedbackComment,
    FeedbackValidation,
    QuestionAuditTrail,
    ReviewEvent,
)


def _dsn() -> str:
    """Build PostgreSQL DSN from environment."""
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5433")
    name = os.environ.get("DB_NAME", "sjqqc_db")
    user = os.environ.get("DB_USER", "sjqqc")
    password = os.environ.get("DB_PASSWORD", "sjqqc")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


async def save_feedback(feedback: FeedbackComment) -> bool:
    """Persist a feedback comment. Returns True on success."""
    try:
        import psycopg

        async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
            await conn.execute(
                "INSERT INTO feedback (id, question_path, author, comment, "
                "target_choice, target_lines, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (
                    feedback.id,
                    feedback.question_path,
                    feedback.author,
                    feedback.comment,
                    feedback.target_choice,
                    json.dumps(list(feedback.target_lines))
                    if feedback.target_lines
                    else None,
                    feedback.created_at,
                ),
            )
        return True
    except Exception as exc:
        logger.debug("DB save_feedback skipped: {}", exc)
        return False


async def save_validation(validation: FeedbackValidation) -> bool:
    """Persist a feedback validation. Returns True on success."""
    try:
        import psycopg

        async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
            await conn.execute(
                "INSERT INTO validations (id, feedback_id, question_path, "
                "verdict, confidence, reasoning, affected_areas, "
                "requires_human_review, suggested_action, raw_llm_response, "
                "created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (
                    validation.id,
                    validation.feedback_id,
                    validation.question_path,
                    validation.verdict,
                    validation.confidence,
                    validation.reasoning,
                    json.dumps(validation.affected_areas),
                    validation.requires_human_review,
                    validation.suggested_action,
                    json.dumps(validation.raw_llm_response)
                    if validation.raw_llm_response
                    else None,
                    validation.created_at,
                ),
            )
        return True
    except Exception as exc:
        logger.debug("DB save_validation skipped: {}", exc)
        return False


async def save_audit_event(event: ReviewEvent, question_path: str) -> bool:
    """Persist a single audit trail event. Returns True on success."""
    try:
        import psycopg

        async with await psycopg.AsyncConnection.connect(_dsn()) as conn:
            await conn.execute(
                "INSERT INTO audit_trail (question_path, event_type, "
                "feedback_id, validation_id, revision_id, summary, data, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    question_path,
                    event.event_type,
                    event.feedback_id,
                    event.validation_id,
                    event.revision_id,
                    event.summary,
                    json.dumps(event.data),
                    event.timestamp,
                ),
            )
        return True
    except Exception as exc:
        logger.debug("DB save_audit_event skipped: {}", exc)
        return False


async def save_audit_trail(trail: QuestionAuditTrail) -> int:
    """Persist all events in an audit trail. Returns count saved."""
    saved = 0
    for event in trail.events:
        if await save_audit_event(event, trail.question_path):
            saved += 1
    if saved:
        logger.info(
            "Persisted {}/{} audit events for {}",
            saved, len(trail.events), trail.question_path,
        )
    return saved
