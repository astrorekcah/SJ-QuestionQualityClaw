"""Linear integration — track question feedback, validation, and revisions.

Every feedback cycle creates or updates a Linear ticket:
  1. Feedback received → ticket created/updated (In Progress)
  2. Validation complete → comment with verdict + reasoning
  3. Revision created → comment with changelog summary + PR link
  4. Question updated → ticket moved to Done
  5. Escalated → ticket flagged for human review
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    QuestionRevision,
    QuestionState,
)

LINEAR_API_URL = "https://api.linear.app/graphql"

STATE_MAP: dict[QuestionState, str] = {
    QuestionState.ACTIVE: "Backlog",
    QuestionState.FEEDBACK_RECEIVED: "Triage",
    QuestionState.UNDER_REVIEW: "In Progress",
    QuestionState.REVISION: "In Progress",
    QuestionState.UPDATED: "Done",
    QuestionState.REJECTED: "Canceled",
}


class LinearClient:
    """Manage Linear tickets for the question feedback pipeline."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        team_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        self.team_id = team_id or os.environ.get("LINEAR_TEAM_ID", "")
        self._state_ids: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # GraphQL
    # ------------------------------------------------------------------

    async def _query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                LINEAR_API_URL, headers=headers, json=payload
            )
            resp.raise_for_status()
            result = resp.json()

        if "errors" in result:
            logger.error("Linear API errors: {}", result["errors"])
            raise RuntimeError(f"Linear API error: {result['errors']}")
        return result.get("data", {})

    async def _get_state_ids(self) -> dict[str, str]:
        if self._state_ids is not None:
            return self._state_ids
        query = """
        query TeamStates($teamId: String!) {
            team(id: $teamId) {
                states { nodes { id name } }
            }
        }
        """
        data = await self._query(query, {"teamId": self.team_id})
        nodes = data.get("team", {}).get("states", {}).get("nodes", [])
        self._state_ids = {n["name"]: n["id"] for n in nodes}
        return self._state_ids

    async def _resolve_state_id(self, state: QuestionState) -> str | None:
        name = STATE_MAP.get(state)
        if not name:
            return None
        ids = await self._get_state_ids()
        return ids.get(name)

    # ------------------------------------------------------------------
    # Ticket lifecycle
    # ------------------------------------------------------------------

    async def create_feedback_ticket(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
    ) -> str:
        """Create a ticket when feedback is received. Returns ticket ID."""
        state_id = await self._resolve_state_id(
            QuestionState.FEEDBACK_RECEIVED
        )

        mutation = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue { id identifier url }
            }
        }
        """
        desc = self._feedback_ticket_description(question, feedback)
        variables = {
            "input": {
                "teamId": self.team_id,
                "title": f"[Feedback] {question.title}",
                "description": desc,
                "priority": 2,
                **({"stateId": state_id} if state_id else {}),
            }
        }

        data = await self._query(mutation, variables)
        issue = data.get("issueCreate", {}).get("issue", {})
        ticket_id = issue.get("id", "")
        identifier = issue.get("identifier", "")
        logger.info(
            "Created Linear ticket {} for feedback on {}",
            identifier, question.question_id,
        )
        return ticket_id

    async def update_state(
        self, ticket_id: str, state: QuestionState
    ) -> None:
        """Transition ticket to a new workflow state."""
        state_id = await self._resolve_state_id(state)
        if not state_id:
            logger.warning("No Linear state for {}", state)
            return
        mutation = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) { success }
        }
        """
        await self._query(mutation, {
            "id": ticket_id,
            "input": {"stateId": state_id},
        })
        logger.info("Ticket {} → {}", ticket_id, state)

    async def post_validation(
        self,
        ticket_id: str,
        validation: FeedbackValidation,
    ) -> None:
        """Post validation results as a ticket comment."""
        body = self._validation_comment(validation)
        await self._post_comment(ticket_id, body)

    async def post_revision(
        self,
        ticket_id: str,
        revision: QuestionRevision,
        *,
        pr_url: str | None = None,
    ) -> None:
        """Post revision changelog as a ticket comment."""
        body = self._revision_comment(revision, pr_url)
        await self._post_comment(ticket_id, body)

    async def post_escalation(
        self,
        ticket_id: str,
        reason: str,
    ) -> None:
        """Post escalation notice when human review is needed."""
        body = f"## Human Review Required\n\n{reason}"
        await self._post_comment(ticket_id, body)

    async def _post_comment(self, ticket_id: str, body: str) -> None:
        mutation = """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) { success }
        }
        """
        await self._query(mutation, {
            "input": {"issueId": ticket_id, "body": body},
        })

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _feedback_ticket_description(
        self, q: AssessmentQuestion, fb: FeedbackComment
    ) -> str:
        return "\n".join([
            f"**Question**: {q.title}",
            f"**Path**: `{q.path}`",
            f"**Language**: {q.language}",
            f"**Type**: {q.prompt.typeId}",
            f"**Current Answer**: {q.correct_answer_key}",
            "",
            "### Feedback",
            f"> {fb.comment}",
            f"**Author**: {fb.author}",
            *([f"**Target choice**: {fb.target_choice}"]
              if fb.target_choice else []),
        ])

    def _validation_comment(self, v: FeedbackValidation) -> str:
        emoji = {
            "valid": "✅", "partially_valid": "⚠️",
            "invalid": "❌", "unclear": "❓",
        }
        lines = [
            f"## Validation: {emoji.get(v.verdict, '❓')} {v.verdict.upper()}",
            f"**Confidence**: {v.confidence:.0%}",
            f"**Action**: {v.suggested_action}",
            "",
            "### Reasoning",
            v.reasoning,
            "",
            f"**Affected areas**: {', '.join(v.affected_areas)}",
        ]
        if v.requires_human_review:
            lines.append("**Escalated**: human review required")
        return "\n".join(lines)

    def _revision_comment(
        self, r: QuestionRevision, pr_url: str | None
    ) -> str:
        lines = [
            "## Revision Created",
            "",
            "### Changes",
        ]
        for change in r.changes_made:
            lines.append(f"- {change}")
        lines.append(f"\n**Rationale**: {r.rationale}")

        if r.changelog:
            cl = r.changelog
            lines.append("\n### Changelog")
            lines.append(
                f"- Strategies: {', '.join(cl.strategies_used)}"
            )
            lines.append(f"- Fields changed: {cl.total_fields_changed}")
            summary = cl.summary
            for area, changed in summary.items():
                icon = "✏️" if changed else "—"
                lines.append(f"- {icon} {area}")

        if pr_url:
            lines.append(f"\n**GitHub PR**: {pr_url}")

        return "\n".join(lines)
