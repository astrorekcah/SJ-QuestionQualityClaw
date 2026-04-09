#!/usr/bin/env python3
"""End-to-end test: load questions, validate, test tools, optionally run live LLM.

Usage:
    python scripts/test_e2e.py                    # Offline tests only
    python scripts/test_e2e.py --live              # Include live OpenRouter calls
    python scripts/test_e2e.py --live --feedback "The answer is wrong"

Drop question JSON files into questions/ directory before running.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from sjqqc.changelog import diff_fields
from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
)
from sjqqc.tools import (
    export_platform_json,
    update_answer,
    update_code,
    update_stem,
    validate_roundtrip,
    validate_step,
)

load_dotenv()
console = Console()

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"


# ---------------------------------------------------------------------------
# Phase 1: Load + validate all questions (offline)
# ---------------------------------------------------------------------------

def phase1_load_and_validate() -> list[AssessmentQuestion]:
    """Load all question files and validate format."""
    console.print("\n[bold cyan]═══ Phase 1: Load & Validate Questions ═══[/bold cyan]")

    files = sorted(QUESTIONS_DIR.glob("*.json"))
    if not files:
        console.print("[red]No question files found in questions/[/red]")
        console.print(f"[dim]Drop .json files into: {QUESTIONS_DIR}[/dim]")
        return []

    questions: list[AssessmentQuestion] = []
    table = Table(title=f"Questions ({len(files)} files)")
    table.add_column("#", style="dim", width=3)
    table.add_column("Type", width=10)
    table.add_column("Lang", width=6)
    table.add_column("Answer", width=6)
    table.add_column("Choices", width=8)
    table.add_column("Code", width=6)
    table.add_column("Title")

    for i, f in enumerate(files, 1):
        try:
            q = AssessmentQuestion(**json.loads(f.read_text()))
            questions.append(q)
            table.add_row(
                str(i),
                q.prompt.typeId,
                q.language,
                q.correct_answer_key or "?",
                str(len(q.choice_keys())),
                str(len(q.prompt.configuration.code)),
                q.title[:50],
            )
        except Exception as exc:
            console.print(f"[red]✗ Failed to parse {f.name}: {exc}[/red]")

    console.print(table)
    console.print(f"[green]✓ {len(questions)}/{len(files)} loaded successfully[/green]")
    return questions


# ---------------------------------------------------------------------------
# Phase 2: Round-trip export test (offline)
# ---------------------------------------------------------------------------

def phase2_roundtrip(questions: list[AssessmentQuestion]) -> None:
    """Verify every question survives export → re-parse."""
    console.print("\n[bold cyan]═══ Phase 2: Round-Trip Export ═══[/bold cyan]")

    passed = 0
    for q in questions:
        try:
            exported = export_platform_json(q)
            reparsed = AssessmentQuestion(**json.loads(exported))
            assert q.to_platform_json() == reparsed.to_platform_json()
            passed += 1
        except Exception as exc:
            console.print(f"[red]✗ {q.question_id}: {exc}[/red]")

    console.print(f"[green]✓ {passed}/{len(questions)} round-trip verified[/green]")


# ---------------------------------------------------------------------------
# Phase 3: Tool mutations test (offline)
# ---------------------------------------------------------------------------

def phase3_tools(questions: list[AssessmentQuestion]) -> None:
    """Test mutation tools on each question."""
    console.print("\n[bold cyan]═══ Phase 3: Tool Mutations ═══[/bold cyan]")

    for q in questions:
        # Test update_answer
        keys = q.choice_keys()
        alt_key = [k for k in keys if k != q.correct_answer_key][0]
        updated, change = update_answer(q, alt_key, strategy="test")
        val = validate_step(q, updated)
        assert val.passed, f"update_answer failed validation: {val.errors}"

        # Test update_stem
        updated2, _ = update_stem(q, "Test stem replacement", strategy="test")
        val2 = validate_step(q, updated2)
        assert val2.passed, f"update_stem failed validation: {val2.errors}"

        # Test update_code (if code exists)
        if q.prompt.configuration.code:
            updated3, _ = update_code(q, 0, "# test line", strategy="test")
            val3 = validate_step(q, updated3)
            assert val3.passed, f"update_code failed validation: {val3.errors}"

        # Test changelog
        updated4, fc = update_answer(q, alt_key, strategy="test")
        changes = diff_fields(q, updated4)
        assert len(changes) >= 1

    console.print(f"[green]✓ {len(questions)} questions: tools + validation passed[/green]")


# ---------------------------------------------------------------------------
# Phase 4: Database connectivity (offline)
# ---------------------------------------------------------------------------

def phase4_database() -> None:
    """Verify database is reachable."""
    console.print("\n[bold cyan]═══ Phase 4: Database ═══[/bold cyan]")

    import psycopg

    dsn = (
        f"host={os.environ.get('DB_HOST', 'localhost')} "
        f"port={os.environ.get('DB_PORT', '5433')} "
        f"dbname={os.environ.get('DB_NAME', 'sjqqc_db')} "
        f"user={os.environ.get('DB_USER', 'sjqqc')} "
        f"password={os.environ.get('DB_PASSWORD', 'sjqqc')}"
    )

    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
            console.print("[green]✓ Connected to database[/green]")
            console.print(f"  Tables: {', '.join(tables)}")
    except Exception as exc:
        console.print(f"[yellow]⚠ Database not available: {exc}[/yellow]")


# ---------------------------------------------------------------------------
# Phase 5: GitHub connectivity (offline-safe)
# ---------------------------------------------------------------------------

def phase5_github() -> None:
    """Verify GitHub token works."""
    console.print("\n[bold cyan]═══ Phase 5: GitHub ═══[/bold cyan]")

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token or token.startswith("{{"):
        console.print("[yellow]⚠ GITHUB_TOKEN not configured[/yellow]")
        return

    from sjqqc.github_client import GitHubQuestionClient

    try:
        ghub = GitHubQuestionClient()
        repo = ghub.repo
        console.print(f"[green]✓ Connected to {repo.full_name}[/green]")
        console.print(f"  Default branch: {repo.default_branch}")
        ghub.close()
    except Exception as exc:
        console.print(f"[red]✗ GitHub error: {exc}[/red]")


# ---------------------------------------------------------------------------
# Phase 6: Live LLM test (requires OpenRouter key)
# ---------------------------------------------------------------------------

async def phase6_live_llm(
    questions: list[AssessmentQuestion],
    feedback_text: str,
) -> None:
    """Run a live feedback processing cycle via OpenRouter."""
    console.print("\n[bold cyan]═══ Phase 6: Live LLM (OpenRouter) ═══[/bold cyan]")

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key or api_key.startswith("{{"):
        console.print("[yellow]⚠ OPENROUTER_API_KEY not configured — skipping[/yellow]")
        return

    from sjqqc.reviewer import QuestionReviewer

    q = questions[0]  # Test with first question
    feedback = FeedbackComment(
        question_path=q.path,
        comment=feedback_text,
    )

    console.print(f"Question: {q.title}")
    console.print(f"Feedback: {feedback_text}")
    console.print()

    reviewer = QuestionReviewer()

    # Validate
    console.print("[dim]Validating feedback...[/dim]")
    validation = await reviewer.validate_feedback(q, feedback)

    emoji = {"valid": "✅", "partially_valid": "⚠️", "invalid": "❌", "unclear": "❓"}
    console.print(
        f"{emoji.get(validation.verdict, '❓')} "
        f"[bold]{validation.verdict.upper()}[/bold] "
        f"(confidence: {validation.confidence:.0%})"
    )
    console.print(f"[dim]{validation.reasoning[:200]}[/dim]")
    console.print(f"Action: {validation.suggested_action}")

    # If valid, run pipeline
    if validation.verdict in ("valid", "partially_valid"):
        console.print("\n[dim]Running improvement pipeline...[/dim]")
        revision = await reviewer.improve_question(q, feedback, validation)

        console.print("[green]✓ Revision created[/green]")
        console.print(f"  Rationale: {revision.rationale}")
        for change in revision.changes_made:
            console.print(f"  • {change}")

        if revision.changelog:
            cl = revision.changelog
            console.print(f"  Strategies: {', '.join(cl.strategies_used)}")
            console.print(f"  Fields changed: {cl.total_fields_changed}")

        # Verify round-trip
        validate_roundtrip(q, revision.revised)
        console.print("[green]✓ Round-trip validated[/green]")

        # Export
        out_path = QUESTIONS_DIR / f"{q.question_id}_revised.json"
        out_path.write_text(export_platform_json(revision.revised))
        console.print(f"[green]✓ Exported: {out_path.name}[/green]")
    else:
        console.print("[yellow]Feedback not valid — no revision produced[/yellow]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    live = "--live" in args
    feedback_text = "The correct answer appears to be wrong"

    # Extract custom feedback
    if "--feedback" in args:
        idx = args.index("--feedback")
        if idx + 1 < len(args):
            feedback_text = " ".join(args[idx + 1:])

    console.print("[bold]SJ-QuestionQualityClaw End-to-End Test[/bold]")
    console.print(f"Questions dir: {QUESTIONS_DIR}")
    console.print(f"Live mode: {'YES' if live else 'NO'}")
    console.print()

    # Offline phases
    questions = phase1_load_and_validate()
    if not questions:
        console.print("\n[red]No questions to test. "
                      "Drop .json files into questions/[/red]")
        sys.exit(1)

    phase2_roundtrip(questions)
    phase3_tools(questions)
    phase4_database()
    phase5_github()

    # Live phase (optional)
    if live:
        asyncio.run(phase6_live_llm(questions, feedback_text))
    else:
        console.print(
            "\n[dim]Skipping live LLM test. "
            "Run with --live to test OpenRouter.[/dim]"
        )

    console.print("\n[bold green]═══ All phases complete ═══[/bold green]")


if __name__ == "__main__":
    main()
