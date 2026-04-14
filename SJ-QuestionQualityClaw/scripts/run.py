#!/usr/bin/env python3
"""SJ-QuestionQualityClaw CLI.

Usage:
    python scripts/run.py assess                              # Bank-wide quality report
    python scripts/run.py process <file> "feedback text"      # Validate + improve one question
    python scripts/run.py quality <file>                      # LLM quality check on one question
    python scripts/run.py export  <file>                      # Export platform JSON
    python scripts/run.py batch-process "feedback" [--dir D]  # Process all questions with feedback
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from sjqqc.models import AssessmentQuestion, FeedbackComment
from sjqqc.quality import assess_bank
from sjqqc.tools import export_platform_json

load_dotenv()
console = Console()

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"


def _load_questions(directory: Path | None = None) -> list[AssessmentQuestion]:
    d = directory or QUESTIONS_DIR
    files = sorted(d.glob("*.json"))
    questions = []
    for f in files:
        if f.name.endswith("_revised.json"):
            continue
        try:
            questions.append(AssessmentQuestion(**json.loads(f.read_text())))
        except Exception as exc:
            console.print(f"[red]Failed to load {f.name}: {exc}[/red]")
    return questions


# ---------------------------------------------------------------------------
# assess
# ---------------------------------------------------------------------------

def cmd_assess() -> None:
    """Bank-wide structural quality assessment."""
    questions = _load_questions()
    if not questions:
        console.print("[red]No questions in questions/[/red]")
        return

    report = assess_bank(questions)

    console.print()
    console.print("[bold]Bank Quality Assessment[/bold]")
    console.print(f"  Questions: {report.total_questions}")
    console.print(
        f"  Passing: {report.passing_questions}/{report.total_questions} "
        f"({report.bank_pass_rate:.0%})"
    )
    console.print(f"  Average score: {report.average_score:.1f}/10")
    console.print()

    table = Table(title="Per-Question Results")
    table.add_column("Verdict", width=3)
    table.add_column("ID", style="dim")
    table.add_column("Score", justify="right", width=6)
    table.add_column("Type", width=12)
    table.add_column("Lang", width=8)
    table.add_column("Issues")

    for sc in report.score_cards:
        emoji = {"pass": "✅", "needs_revision": "⚠️", "fail": "❌"}
        issue_text = "; ".join(sc.issues[:2]) if sc.issues else "—"
        table.add_row(
            emoji.get(sc.verdict, "?"),
            sc.question_id[:25],
            f"{sc.overall_score:.1f}",
            sc.type_id,
            sc.language,
            issue_text[:60],
        )

    console.print(table)

    console.print("\n[bold]Dimension Pass Rates[/bold]")
    for name, rate in report.weakest_dimensions:
        bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
        console.print(f"  {name:<25} {bar} {rate:.0%}")

    pq = report.priority_queue
    if pq:
        console.print(f"\n[bold]Priority Queue ({len(pq)} need work)[/bold]")
        for i, sc in enumerate(pq[:5], 1):
            console.print(
                f"  {i}. {sc.question_id} "
                f"({len(sc.critical_failures)} critical, "
                f"{len(sc.major_failures)} major)"
            )


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

async def cmd_process(question_path: str, feedback_text: str) -> None:
    """Validate feedback + run improvement pipeline on one question."""
    from sjqqc.reviewer import QuestionReviewer

    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    feedback = FeedbackComment(
        question_path=question.path, comment=feedback_text
    )
    reviewer = QuestionReviewer()

    console.print(f"[bold]Question:[/bold] {question.title}")
    console.print(f"[bold]Feedback:[/bold] {feedback_text}")
    console.print()

    validation, revision = await reviewer.process_feedback(question, feedback)

    emoji = {"valid": "✅", "partially_valid": "⚠️", "invalid": "❌", "unclear": "❓"}
    console.print(
        f"{emoji.get(validation.verdict, '❓')} "
        f"[bold]{validation.verdict.upper()}[/bold] "
        f"(confidence: {validation.confidence:.0%})"
    )
    console.print(f"[dim]{validation.reasoning[:200]}[/dim]")

    if revision:
        console.print(f"\n[bold]Revision:[/bold] {revision.rationale}")
        for change in revision.changes_made:
            console.print(f"  • {change}")
        if revision.changelog:
            cl = revision.changelog
            console.print(f"\n  Strategies: {', '.join(cl.strategies_used)}")
            console.print(f"  Fields changed: {cl.total_fields_changed}")
            for area, changed in cl.summary.items():
                console.print(f"  {'✏️' if changed else '—'} {area}")

        output_path = Path(question_path).stem + "_revised.json"
        Path(output_path).write_text(export_platform_json(revision.revised))
        console.print(f"\n[green]Exported:[/green] {output_path}")
    else:
        console.print("\n[yellow]No revision produced.[/yellow]")


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------

async def cmd_quality(question_path: str) -> None:
    """LLM quality check on one question."""
    from sjqqc.reviewer import QuestionReviewer

    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    reviewer = QuestionReviewer()

    console.print(f"[bold]Quality check:[/bold] {question.title}")
    result = await reviewer.quality_check(question)

    score = result.get("overall_score", 0)
    verdict = result.get("verdict", "unknown")
    console.print(f"\n[bold]{verdict.upper()}[/bold] ({score}/10)")

    # Handle new format: {"dimensions": {"name": {"score", "notes"}}}
    dimensions = result.get("dimensions", {})
    if isinstance(dimensions, dict) and dimensions:
        from config.quality_baseline import get_baseline

        baseline = get_baseline(question.prompt.typeId)
        for dim in baseline.dimensions:
            d = dimensions.get(dim.name, {})
            if isinstance(d, dict):
                dim_score = d.get("score", "?")
                notes = d.get("notes", "")
                passed = (
                    isinstance(dim_score, (int, float))
                    and dim_score >= dim.pass_threshold
                )
                icon = "✅" if passed else "❌"
                console.print(
                    f"  {icon} {dim.name}: {dim_score}/10 "
                    f"(pass ≥{dim.pass_threshold}) — "
                    f"{notes[:70]}"
                )
    else:
        # Fallback: old flat format
        for dim in (
            "technical_accuracy", "stem_clarity", "choice_quality",
            "code_quality", "difficulty_calibration",
        ):
            d = result.get(dim, {})
            if isinstance(d, dict):
                console.print(
                    f"  {dim}: {d.get('score', '?')}/10 — "
                    f"{d.get('notes', '')[:80]}"
                )

    issues = result.get("issues_found", [])
    if issues:
        console.print("\n[bold]Issues:[/bold]")
        for issue in issues:
            console.print(f"  • {issue}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(question_path: str) -> None:
    """Export question as platform JSON."""
    question = AssessmentQuestion(**json.loads(Path(question_path).read_text()))
    platform_json = export_platform_json(question)
    output_path = Path(question_path).stem + "_exported.json"
    Path(output_path).write_text(platform_json)
    console.print(
        f"[green]Exported:[/green] {output_path} ({len(platform_json)} bytes)"
    )


# ---------------------------------------------------------------------------
# batch-process
# ---------------------------------------------------------------------------

async def cmd_batch_process(
    feedback_text: str, directory: Path | None = None
) -> None:
    """Process feedback across all questions in the bank."""
    from sjqqc.reviewer import QuestionReviewer

    questions = _load_questions(directory)
    if not questions:
        console.print("[red]No questions found[/red]")
        return

    reviewer = QuestionReviewer()
    console.print(
        f"[bold]Batch: {len(questions)} questions[/bold]"
    )
    console.print(f"[bold]Feedback:[/bold] {feedback_text}")
    console.print()

    for i, q in enumerate(questions, 1):
        console.print(f"[dim]({i}/{len(questions)})[/dim] {q.title[:50]}")
        feedback = FeedbackComment(
            question_path=q.path, comment=feedback_text
        )
        try:
            validation, revision = await reviewer.process_feedback(
                q, feedback
            )
            emoji = {
                "valid": "✅", "partially_valid": "⚠️",
                "invalid": "❌", "unclear": "❓",
            }
            status = emoji.get(validation.verdict, "?")
            revised = "→ revised" if revision else ""
            console.print(
                f"  {status} {validation.verdict} "
                f"({validation.confidence:.0%}) {revised}"
            )
        except Exception as exc:
            console.print(f"  [red]ERROR: {exc}[/red]")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        console.print("[bold]SJ-QuestionQualityClaw[/bold]")
        console.print()
        console.print("Commands:")
        console.print("  assess                           Bank quality report")
        console.print('  process <file> "feedback"        Validate + improve')
        console.print("  quality <file>                   LLM quality check")
        console.print("  export  <file>                   Export platform JSON")
        console.print('  batch-process "feedback"         Process all questions')
        console.print("  telegram                         Start Telegram bot")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "assess":
        cmd_assess()
    elif cmd == "process":
        if len(sys.argv) < 4:
            console.print('[red]Usage: process <file> "feedback"[/red]')
            sys.exit(1)
        asyncio.run(cmd_process(sys.argv[2], " ".join(sys.argv[3:])))
    elif cmd == "quality":
        if len(sys.argv) < 3:
            console.print("[red]Usage: quality <file>[/red]")
            sys.exit(1)
        asyncio.run(cmd_quality(sys.argv[2]))
    elif cmd == "export":
        if len(sys.argv) < 3:
            console.print("[red]Usage: export <file>[/red]")
            sys.exit(1)
        cmd_export(sys.argv[2])
    elif cmd == "batch-process":
        if len(sys.argv) < 3:
            console.print('[red]Usage: batch-process "feedback"[/red]')
            sys.exit(1)
        asyncio.run(cmd_batch_process(" ".join(sys.argv[2:])))
    elif cmd == "telegram":
        from sjqqc.telegram_bridge import main as telegram_main

        asyncio.run(telegram_main())
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
