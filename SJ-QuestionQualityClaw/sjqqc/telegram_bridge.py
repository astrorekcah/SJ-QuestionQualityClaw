"""Telegram bridge — forward messages as FeedbackComment objects.

Polls the Telegram Bot API for messages. When a message matches the format
`/feedback <question_id> <comment>`, it:
  1. Finds the question in the questions directory
  2. Creates a FeedbackComment
  3. Runs process_feedback()
  4. Replies with the validation result + revision status

Also supports:
  /assess — run bank assessment and reply with summary
  /status — show system status
  /help   — show available commands

Uses raw httpx (no extra dependency) for the Telegram Bot API.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from sjqqc.loader import load_all_with_feedback, load_question
from sjqqc.models import AssessmentQuestion, FeedbackComment
from sjqqc.quality import assess_bank
from sjqqc.reviewer import QuestionReviewer
from sjqqc.tools import export_platform_json

TELEGRAM_API = "https://api.telegram.org"
QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"


class TelegramBridge:
    """Polls Telegram for messages and processes them as feedback."""

    def __init__(
        self,
        bot_token: str | None = None,
        owner_id: int | None = None,
        questions_dir: Path | None = None,
    ) -> None:
        self.token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.owner_id = owner_id or int(
            os.environ.get("TELEGRAM_OWNER_ID", "0")
        )
        self.questions_dir = questions_dir or QUESTIONS_DIR
        self._offset = 0
        self._reviewer = QuestionReviewer()

        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN not set. "
                "Get one from @BotFather on Telegram."
            )

    # ------------------------------------------------------------------
    # Telegram API helpers
    # ------------------------------------------------------------------

    async def _api(
        self, method: str, **params: Any
    ) -> dict[str, Any]:
        """Call a Telegram Bot API method."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{self.token}/{method}",
                json={k: v for k, v in params.items() if v is not None},
            )
            resp.raise_for_status()
            return resp.json()

    async def _send(self, chat_id: int, text: str) -> None:
        """Send a message, truncating if needed."""
        # Telegram max message length is 4096
        if len(text) > 4000:
            text = text[:4000] + "\n\n[truncated]"
        await self._api(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
        )

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Poll for new messages."""
        result = await self._api(
            "getUpdates",
            offset=self._offset,
            timeout=30,
        )
        updates = result.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_feedback(
        self, chat_id: int, args: str
    ) -> None:
        """Handle /feedback <question_id> <comment>."""
        parts = args.strip().split(" ", 1)
        if len(parts) < 2:
            await self._send(
                chat_id,
                "Usage: `/feedback <question_id> <comment>`\n"
                "Example: `/feedback sc-aa-Ruby-863-2-v2 "
                "The answer should be D`",
            )
            return

        question_id, comment = parts

        # Find the question file
        question = self._find_question(question_id)
        if not question:
            await self._send(
                chat_id,
                f"Question `{question_id}` not found in questions/",
            )
            return

        await self._send(
            chat_id,
            f"Processing feedback on *{question.title}*...",
        )

        # Create feedback and process
        feedback = FeedbackComment(
            question_path=question.path,
            comment=comment,
            author="telegram",
        )

        try:
            validation, revision = await self._reviewer.process_feedback(
                question, feedback
            )

            # Build response
            emoji = {
                "valid": "✅", "partially_valid": "⚠️",
                "invalid": "❌", "unclear": "❓",
            }
            lines = [
                f"{emoji.get(validation.verdict, '❓')} "
                f"*{validation.verdict.upper()}* "
                f"({validation.confidence:.0%})",
                "",
                f"_{validation.reasoning[:300]}_",
            ]

            if revision:
                lines.append("")
                lines.append(f"*Revision:* {revision.rationale[:200]}")
                if revision.changelog:
                    cl = revision.changelog
                    lines.append(
                        f"Strategies: {', '.join(cl.strategies_used)}"
                    )
                    lines.append(
                        f"Fields changed: {cl.total_fields_changed}"
                    )

                # Export
                out_path = (
                    self.questions_dir
                    / f"{question_id}_revised.json"
                )
                out_path.write_text(
                    export_platform_json(revision.revised)
                )
                lines.append(f"\nExported: `{out_path.name}`")

            # Cost
            costs = self._reviewer._llm.costs
            lines.append(
                f"\n💰 Cost: ${costs.total_cost_usd:.4f} "
                f"({costs.total_calls} calls, "
                f"{costs.cached_calls} cached)"
            )

            await self._send(chat_id, "\n".join(lines))

        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")
            logger.error("Feedback processing failed: {}", exc)

    async def _handle_assess(self, chat_id: int) -> None:
        """Handle /assess — bank quality report."""
        pairs = load_all_with_feedback(self.questions_dir)
        questions = [q for q, _ in pairs]

        if not questions:
            await self._send(chat_id, "No questions in questions/")
            return

        report = assess_bank(questions)
        lines = [
            "*Bank Assessment*",
            f"Questions: {report.total_questions}",
            f"Passing: {report.passing_questions}/{report.total_questions} "
            f"({report.bank_pass_rate:.0%})",
            f"Avg score: {report.average_score:.1f}/10",
        ]

        pq = report.priority_queue
        if pq:
            lines.append(f"\n*Priority queue ({len(pq)} need work):*")
            for sc in pq[:5]:
                lines.append(
                    f"  {sc.question_id}: "
                    f"{len(sc.critical_failures)} critical"
                )

        await self._send(chat_id, "\n".join(lines))

    async def _handle_status(self, chat_id: int) -> None:
        """Handle /status."""
        pairs = load_all_with_feedback(self.questions_dir)
        with_fb = sum(1 for _, fb in pairs if fb is not None)
        costs = self._reviewer._llm.costs

        lines = [
            "*QuestionQualityClaw Status*",
            f"Questions: {len(pairs)}",
            f"With feedback: {with_fb}",
            f"LLM calls: {costs.total_calls} "
            f"({costs.cached_calls} cached)",
            f"Total cost: ${costs.total_cost_usd:.4f}",
            f"Model: {self._reviewer.model}",
        ]
        await self._send(chat_id, "\n".join(lines))

    async def _handle_help(self, chat_id: int) -> None:
        """Handle /help."""
        await self._send(chat_id, (
            "*SJ-QuestionQualityClaw*\n\n"
            "Commands:\n"
            "`/feedback <id> <comment>` — validate + improve\n"
            "`/assess` — bank quality report\n"
            "`/status` — system status + costs\n"
            "`/help` — this message"
        ))

    # ------------------------------------------------------------------
    # Question lookup
    # ------------------------------------------------------------------

    def _find_question(
        self, question_id: str
    ) -> AssessmentQuestion | None:
        """Find a question by ID in the questions directory."""
        for f in self.questions_dir.glob("*.json"):
            if f.name.endswith(("_revised.json", ".feedback.json")):
                continue
            try:
                q = load_question(f)
                if q.question_id == question_id:
                    return q
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start polling for Telegram messages."""
        # Verify bot works
        me = await self._api("getMe")
        bot_name = me.get("result", {}).get("username", "unknown")
        logger.info("Telegram bridge started: @{}", bot_name)

        while True:
            try:
                updates = await self._get_updates()
                for update in updates:
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")

                    if not chat_id or not text:
                        continue

                    # Security: only respond to owner
                    if self.owner_id and chat_id != self.owner_id:
                        logger.warning(
                            "Ignoring message from non-owner: {}",
                            chat_id,
                        )
                        continue

                    # Route commands
                    if text.startswith("/feedback"):
                        await self._handle_feedback(
                            chat_id, text[len("/feedback"):].strip()
                        )
                    elif text.startswith("/assess"):
                        await self._handle_assess(chat_id)
                    elif text.startswith("/status"):
                        await self._handle_status(chat_id)
                    elif text.startswith("/help") or text.startswith("/start"):
                        await self._handle_help(chat_id)
                    else:
                        await self._send(
                            chat_id,
                            "Send /help for available commands.",
                        )

            except httpx.TimeoutException:
                continue  # Normal for long polling
            except Exception as exc:
                logger.error("Telegram polling error: {}", exc)
                await asyncio.sleep(5)


async def main() -> None:
    """Entry point for running the Telegram bridge."""
    from dotenv import load_dotenv

    load_dotenv()
    bridge = TelegramBridge()
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
