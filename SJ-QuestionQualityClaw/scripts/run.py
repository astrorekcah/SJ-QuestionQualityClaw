#!/usr/bin/env python3
"""SJ-QuestionQualityClaw Runner — Start the question review system.

Usage:
    python scripts/run.py review <question.json>     # Single review
    python scripts/run.py multi <question.json>      # Multi-pass review
    python scripts/run.py batch <domain>             # Batch review a domain
    python scripts/run.py revise <question.json>     # Auto-revise from feedback

Prerequisites:
    source .venv/bin/activate
    cp .env.example .env  # Fill in API keys
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.table import Table

from sjqqc.models import Question, ReviewVerdict
from sjqqc.reviewer import QuestionReviewer

load_dotenv()
console = Console()


async def cmd_review(path: str) -> None:
    """Run a single-pass review on a question file."""
    question = Question(**json.loads(Path(path).read_text()))
    reviewer = QuestionReviewer()
    review = await reviewer.review(question)

    _print_review(review)


async def cmd_multi(path: str) -> None:
    """Run multi-pass review on a question file."""
    question = Question(**json.loads(Path(path).read_text()))
    reviewer = QuestionReviewer()
    feedback = await reviewer.multi_pass(question, passes=3)

    console.print(f"\n[bold]Consensus: {_verdict_emoji(feedback.consensus_verdict)} "
                  f"{feedback.consensus_verdict.upper()}[/bold] "
                  f"(avg {feedback.average_score:.1f}/10)")

    if feedback.disputed_criteria:
        console.print(f"[yellow]⚠ Disputed criteria: {', '.join(feedback.disputed_criteria)}[/yellow]")

    for i, review in enumerate(feedback.reviews):
        console.print(f"\n--- Pass {i + 1} ---")
        _print_review(review)


async def cmd_batch(domain: str) -> None:
    """Batch review all questions in a domain (reads from local files)."""
    questions_dir = Path(f"questions/{domain}")
    if not questions_dir.exists():
        console.print(f"[red]No questions directory: {questions_dir}[/red]")
        return

    questions = []
    for f in questions_dir.glob("*.json"):
        questions.append(Question(**json.loads(f.read_text())))

    if not questions:
        console.print(f"[yellow]No questions found in {questions_dir}[/yellow]")
        return

    reviewer = QuestionReviewer()
    report = await reviewer.batch(questions)

    table = Table(title=f"Batch Review: {domain}")
    table.add_column("ID", style="dim")
    table.add_column("Title")
    table.add_column("Verdict")
    table.add_column("Score", justify="right")
    table.add_column("Top Issue")

    for entry in report.entries:
        table.add_row(
            entry.question_id[:8],
            entry.title,
            f"{_verdict_emoji(entry.verdict)} {entry.verdict}",
            f"{entry.score:.1f}",
            entry.top_issue[:50],
        )

    console.print(table)
    console.print(f"\n{report.passed}/{report.total} passed ({report.pass_rate:.0f}%), "
                  f"avg score {report.average_score:.1f}")


async def cmd_revise(path: str) -> None:
    """Auto-revise a question based on review feedback."""
    question = Question(**json.loads(Path(path).read_text()))
    reviewer = QuestionReviewer()

    console.print("[dim]Running initial review...[/dim]")
    review = await reviewer.review(question)
    _print_review(review)

    if review.verdict == ReviewVerdict.PASS:
        console.print("[green]Question already passes — no revision needed.[/green]")
        return

    console.print("\n[dim]Generating revision...[/dim]")
    revised = await reviewer.revise(question, review)
    console.print(f"\n[bold]Revised Question:[/bold]")
    console.print(revised.model_dump_json(indent=2))


def _verdict_emoji(verdict: ReviewVerdict) -> str:
    return {"pass": "✅", "needs_revision": "⚠️", "fail": "❌"}.get(verdict, "❓")


def _print_review(review) -> None:
    console.print(f"\n{_verdict_emoji(review.verdict)} [bold]{review.verdict.upper()}[/bold] "
                  f"({review.overall_score:.1f}/10)")
    console.print(f"[dim]{review.summary}[/dim]")
    for cs in review.criterion_scores:
        bar = "█" * int(cs.score) + "░" * (10 - int(cs.score))
        console.print(f"  {cs.criterion:<22} {bar} {cs.score:.0f}/10  {cs.feedback}")
    if review.suggestions:
        console.print("\n[bold]Suggestions:[/bold]")
        for s in review.suggestions:
            console.print(f"  • {s}")


def main() -> None:
    if len(sys.argv) < 2:
        console.print("Usage: python scripts/run.py <command> [args]")
        console.print("  review <file>   — Single review")
        console.print("  multi  <file>   — Multi-pass review")
        console.print("  batch  <domain> — Batch review domain")
        console.print("  revise <file>   — Auto-revise from feedback")
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    commands = {
        "review": cmd_review,
        "multi": cmd_multi,
        "batch": cmd_batch,
        "revise": cmd_revise,
    }

    if cmd not in commands:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        sys.exit(1)

    asyncio.run(commands[cmd](arg))


if __name__ == "__main__":
    main()
