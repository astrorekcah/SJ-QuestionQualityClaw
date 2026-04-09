#!/usr/bin/env python3
"""SJ-QuestionQualityClaw CLI — feedback-driven question improvement.

Usage:
    python scripts/run.py process <question.json> "feedback text"
    python scripts/run.py quality <question.json>
    python scripts/run.py export <question.json>

Prerequisites:
    source .venv/bin/activate
    cp .env.example .env  # Fill in OPENROUTER_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console

from sjqqc.models import AssessmentQuestion, FeedbackComment
from sjqqc.reviewer import QuestionReviewer
from sjqqc.tools import export_platform_json

load_dotenv()
console = Console()


async def cmd_process(question_path: str, feedback_text: str) -> None:
    """Process feedback: validate → pipeline → export."""
    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    feedback = FeedbackComment(
        question_path=question.path,
        comment=feedback_text,
    )

    reviewer = QuestionReviewer()

    console.print(f"[bold]Question:[/bold] {question.title}")
    console.print(f"[bold]Feedback:[/bold] {feedback_text}")
    console.print()

    # Validate
    console.print("[dim]Validating feedback...[/dim]")
    validation, revision = await reviewer.process_feedback(question, feedback)

    emoji = {"valid": "✅", "partially_valid": "⚠️", "invalid": "❌", "unclear": "❓"}
    console.print(
        f"\n{emoji.get(validation.verdict, '❓')} "
        f"[bold]{validation.verdict.upper()}[/bold] "
        f"(confidence: {validation.confidence:.0%})"
    )
    console.print(f"[dim]{validation.reasoning}[/dim]")

    if revision:
        console.print(f"\n[bold]Revision:[/bold] {revision.rationale}")
        for change in revision.changes_made:
            console.print(f"  • {change}")

        if revision.changelog:
            cl = revision.changelog
            console.print(f"\n[bold]Changelog:[/bold]")
            console.print(f"  Strategies: {', '.join(cl.strategies_used)}")
            console.print(f"  Fields changed: {cl.total_fields_changed}")
            for area, changed in cl.summary.items():
                icon = "✏️" if changed else "—"
                console.print(f"  {icon} {area}")

        # Export
        output_path = Path(question_path).stem + "_revised.json"
        platform_json = export_platform_json(revision.revised)
        Path(output_path).write_text(platform_json)
        console.print(f"\n[green]Exported:[/green] {output_path}")
    else:
        console.print("\n[yellow]No revision produced.[/yellow]")


async def cmd_quality(question_path: str) -> None:
    """Run independent quality check."""
    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    reviewer = QuestionReviewer()

    console.print(f"[bold]Quality check:[/bold] {question.title}")
    result = await reviewer.quality_check(question)

    score = result.get("overall_score", 0)
    verdict = result.get("verdict", "unknown")
    console.print(f"\n[bold]{verdict.upper()}[/bold] ({score}/10)")

    for dim in ("technical_accuracy", "stem_clarity", "choice_quality",
                "code_quality", "difficulty_calibration"):
        d = result.get(dim, {})
        console.print(f"  {dim}: {d.get('score', '?')}/10 — {d.get('notes', '')}")

    issues = result.get("issues_found", [])
    if issues:
        console.print("\n[bold]Issues:[/bold]")
        for issue in issues:
            console.print(f"  • {issue}")


def cmd_export(question_path: str) -> None:
    """Export question as platform JSON (verify round-trip)."""
    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    platform_json = export_platform_json(question)

    output_path = Path(question_path).stem + "_exported.json"
    Path(output_path).write_text(platform_json)
    console.print(f"[green]Exported:[/green] {output_path} ({len(platform_json)} bytes)")


def main() -> None:
    if len(sys.argv) < 3:
        console.print("Usage:")
        console.print('  process <question.json> "feedback text"  — validate + improve')
        console.print("  quality <question.json>                  — quality check")
        console.print("  export  <question.json>                  — export platform JSON")
        sys.exit(1)

    cmd = sys.argv[1]
    arg1 = sys.argv[2]

    if cmd == "process":
        if len(sys.argv) < 4:
            console.print("[red]Missing feedback text[/red]")
            sys.exit(1)
        feedback_text = " ".join(sys.argv[3:])
        asyncio.run(cmd_process(arg1, feedback_text))
    elif cmd == "quality":
        asyncio.run(cmd_quality(arg1))
    elif cmd == "export":
        cmd_export(arg1)
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
