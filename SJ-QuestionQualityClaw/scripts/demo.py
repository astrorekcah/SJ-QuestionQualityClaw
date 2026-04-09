#!/usr/bin/env python3
"""SJ-QuestionQualityClaw Demo — walk through the complete system.

Run:  python scripts/demo.py

This demonstrates:
  1. Load question bank
  2. Structural quality assessment
  3. Pick a question + provide feedback
  4. Validate feedback via OpenRouter
  5. Run improvement pipeline (classify → fix → validate)
  6. Show changelog + export platform JSON
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sjqqc.models import AssessmentQuestion, FeedbackComment
from sjqqc.quality import assess_bank
from sjqqc.tools import export_platform_json

load_dotenv()
console = Console()

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"

# Demo feedback for specific question types
DEMO_FEEDBACK = {
    "mc-block": (
        "The correct answer should be choice D, not C — after the admin "
        "check on line 80, the code falls through to line 84 which returns "
        "the document without any access control for restricted/confidential "
        "documents accessed by non-admin, non-owner users."
    ),
    "mc-line": (
        "The answer points to the wrong line — the actual vulnerability is "
        "the missing tenant boundary check that allows a user to pass any "
        "tenant_id parameter and access records from other tenants."
    ),
    "mc-code": (
        "Choice A is not the correct answer — it's a standard login handler. "
        "Choice C is the real vulnerability because process_wire_transfer "
        "performs a critical financial operation without any authentication check."
    ),
    "mc-generic": (
        "The correct answer oversimplifies RAG — it doesn't just 'enhance' "
        "models, it specifically retrieves relevant context from a knowledge "
        "base at inference time to ground the model's responses in factual data."
    ),
}


def _pause(msg: str = "Press Enter to continue...") -> None:
    """Pause for demo pacing. Skip with --fast flag."""
    if "--fast" not in sys.argv:
        console.input(f"\n[dim]{msg}[/dim]")
    else:
        console.print()


async def main() -> None:
    console.print(Panel.fit(
        "[bold cyan]SJ-QuestionQualityClaw[/bold cyan]\n"
        "Feedback-driven assessment question quality agent",
        border_style="cyan",
    ))
    console.print()

    # ── Step 1: Load questions ──
    console.print("[bold]Step 1: Load Question Bank[/bold]")
    files = sorted(QUESTIONS_DIR.glob("*.json"))
    questions = []
    for f in files:
        if f.name.endswith("_revised.json"):
            continue
        with contextlib.suppress(Exception):
            questions.append(AssessmentQuestion(**json.loads(f.read_text())))

    console.print(f"  Loaded {len(questions)} questions from questions/")

    types = {}
    for q in questions:
        types[q.prompt.typeId] = types.get(q.prompt.typeId, 0) + 1
    console.print(f"  Types: {dict(types)}")

    langs = {}
    for q in questions:
        langs[q.language] = langs.get(q.language, 0) + 1
    console.print(f"  Languages: {dict(langs)}")

    _pause()

    # ── Step 2: Bank assessment ──
    console.print("[bold]Step 2: Structural Quality Assessment[/bold]")
    report = assess_bank(questions)

    console.print(
        f"  {report.passing_questions}/{report.total_questions} passing "
        f"({report.bank_pass_rate:.0%})"
    )
    console.print(f"  Average score: {report.average_score:.1f}/10")

    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=3)
    table.add_column("Question", width=35)
    table.add_column("Type", width=12)
    table.add_column("Score", justify="right", width=6)
    for sc in report.score_cards:
        emoji = {"pass": "✅", "needs_revision": "⚠️", "fail": "❌"}
        table.add_row(
            emoji.get(sc.verdict, "?"),
            sc.question_id[:35],
            sc.type_id,
            f"{sc.overall_score:.1f}",
        )
    console.print(table)

    _pause()

    # ── Step 3: Pick a question + feedback ──
    console.print("[bold]Step 3: Select Question + Feedback[/bold]")

    # Pick first mc-block question for demo
    demo_q = next(
        (q for q in questions if q.prompt.typeId == "mc-block"),
        questions[0],
    )
    feedback_text = DEMO_FEEDBACK.get(demo_q.prompt.typeId, DEMO_FEEDBACK["mc-block"])

    console.print(f"  [bold]Question:[/bold] {demo_q.title}")
    console.print(f"  [bold]Type:[/bold] {demo_q.prompt.typeId}")
    console.print(f"  [bold]Language:[/bold] {demo_q.language}")
    console.print(f"  [bold]Current answer:[/bold] {demo_q.correct_answer_key}")
    console.print()
    console.print(Panel(feedback_text, title="Learner Feedback", border_style="yellow"))

    _pause()

    # ── Step 4: Validate feedback ──
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key or api_key.startswith("{{"):
        console.print(
            "[yellow]⚠ OPENROUTER_API_KEY not set — "
            "skipping live LLM steps[/yellow]"
        )
        console.print(
            "[dim]Set it in .env to see the full pipeline demo[/dim]"
        )
        return

    from sjqqc.reviewer import QuestionReviewer

    reviewer = QuestionReviewer()
    feedback = FeedbackComment(
        question_path=demo_q.path,
        comment=feedback_text,
    )

    console.print("[bold]Step 4: Validate Feedback (OpenRouter)[/bold]")
    start = time.time()
    validation = await reviewer.validate_feedback(demo_q, feedback)
    elapsed = time.time() - start

    emoji = {
        "valid": "✅", "partially_valid": "⚠️",
        "invalid": "❌", "unclear": "❓",
    }
    console.print(
        f"  {emoji.get(validation.verdict, '?')} "
        f"[bold]{validation.verdict.upper()}[/bold] "
        f"(confidence: {validation.confidence:.0%}, {elapsed:.1f}s)"
    )
    console.print(f"  [dim]{validation.reasoning[:200]}[/dim]")
    console.print(f"  Action: {validation.suggested_action}")

    _pause()

    # ── Step 5: Run pipeline ──
    if validation.verdict in ("valid", "partially_valid"):
        console.print("[bold]Step 5: Improvement Pipeline[/bold]")
        console.print("  classify → fix strategies → validate → assemble")
        console.print()

        start = time.time()
        revision = await reviewer.improve_question(
            demo_q, feedback, validation
        )
        elapsed = time.time() - start

        console.print(f"  [green]Pipeline complete[/green] ({elapsed:.1f}s)")
        console.print(f"  Rationale: {revision.rationale}")
        console.print()

        # ── Step 6: Changelog ──
        console.print("[bold]Step 6: Changelog[/bold]")
        if revision.changelog:
            cl = revision.changelog
            console.print(
                f"  Strategies: {', '.join(cl.strategies_used)}"
            )
            console.print(f"  Fields changed: {cl.total_fields_changed}")
            for area, changed in cl.summary.items():
                icon = "✏️" if changed else "—"
                console.print(f"  {icon} {area}")
            console.print()

            for change in revision.changes_made:
                console.print(f"  • {change}")

        _pause()

        # ── Step 7: Export ──
        console.print("[bold]Step 7: Export Platform JSON[/bold]")
        output_path = QUESTIONS_DIR / f"{demo_q.question_id}_demo_revised.json"
        platform_json = export_platform_json(revision.revised)
        output_path.write_text(platform_json)

        console.print(f"  [green]Exported:[/green] {output_path.name}")
        console.print(f"  Size: {len(platform_json)} bytes")
        console.print(
            "  Format: exact platform JSON — directly uploadable"
        )

        # Verify round-trip
        from sjqqc.tools import validate_roundtrip
        validate_roundtrip(demo_q, revision.revised)
        console.print("  [green]✓ Round-trip validated[/green]")
    else:
        console.print(
            "[yellow]Feedback not valid — pipeline skipped[/yellow]"
        )

    console.print()
    console.print(Panel.fit(
        "[bold green]Demo complete[/bold green]",
        border_style="green",
    ))


if __name__ == "__main__":
    asyncio.run(main())
