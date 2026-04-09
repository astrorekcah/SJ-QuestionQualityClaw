"""Linear integration — ticket lifecycle management for question review pipeline."""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

from sjqqc.models import Question, QuestionState, Review

# Linear GraphQL API endpoint
LINEAR_API_URL = "https://api.linear.app/graphql"

# Map question states to Linear workflow state names
STATE_MAP: dict[QuestionState, str] = {
    QuestionState.DRAFT: "Backlog",
    QuestionState.REVIEW: "In Progress",
    QuestionState.REVISION: "In Progress",
    QuestionState.APPROVED: "Done",
    QuestionState.REJECTED: "Canceled",
    QuestionState.PUBLISHED: "Done",
}


class LinearClient:
    """Manage Linear tickets for the question review pipeline."""

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
    # GraphQL helpers
    # ------------------------------------------------------------------

    async def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query against the Linear API."""
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(LINEAR_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

        if "errors" in result:
            logger.error("Linear API errors: {}", result["errors"])
            raise RuntimeError(f"Linear API error: {result['errors']}")

        return result.get("data", {})

    async def _get_state_ids(self) -> dict[str, str]:
        """Fetch workflow state name → ID mapping for the team."""
        if self._state_ids is not None:
            return self._state_ids

        query = """
        query TeamStates($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                    }
                }
            }
        }
        """
        data = await self._query(query, {"teamId": self.team_id})
        nodes = data.get("team", {}).get("states", {}).get("nodes", [])
        self._state_ids = {node["name"]: node["id"] for node in nodes}
        return self._state_ids

    async def _resolve_state_id(self, question_state: QuestionState) -> str | None:
        """Map a QuestionState to a Linear workflow state ID."""
        state_name = STATE_MAP.get(question_state)
        if not state_name:
            return None
        state_ids = await self._get_state_ids()
        return state_ids.get(state_name)

    # ------------------------------------------------------------------
    # Ticket CRUD
    # ------------------------------------------------------------------

    async def create_ticket(
        self,
        question: Question,
        *,
        priority: int = 2,
    ) -> str:
        """Create a Linear ticket for a new question. Returns the ticket ID."""
        state_id = await self._resolve_state_id(question.state)

        mutation = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    url
                }
            }
        }
        """
        variables = {
            "input": {
                "teamId": self.team_id,
                "title": f"[{question.question_type.value}] {question.title}",
                "description": self._ticket_description(question),
                "priority": priority,
                **({"stateId": state_id} if state_id else {}),
                "labelIds": [],
            }
        }

        data = await self._query(mutation, variables)
        issue = data.get("issueCreate", {}).get("issue", {})
        ticket_id = issue.get("id", "")
        identifier = issue.get("identifier", "")

        logger.info("Created Linear ticket {} for question {}", identifier, question.id)
        return ticket_id

    async def update_ticket_state(
        self,
        ticket_id: str,
        new_state: QuestionState,
    ) -> None:
        """Update a ticket's workflow state."""
        state_id = await self._resolve_state_id(new_state)
        if not state_id:
            logger.warning("No Linear state mapping for {}", new_state)
            return

        mutation = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
            }
        }
        """
        await self._query(mutation, {
            "id": ticket_id,
            "input": {"stateId": state_id},
        })
        logger.info("Updated ticket {} to state {}", ticket_id, new_state)

    async def add_review_comment(
        self,
        ticket_id: str,
        review: Review,
    ) -> None:
        """Add a review summary as a comment on the ticket."""
        body = self._review_comment(review)

        mutation = """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
            }
        }
        """
        await self._query(mutation, {
            "input": {
                "issueId": ticket_id,
                "body": body,
            },
        })
        logger.info("Added review comment to ticket {}", ticket_id)

    async def link_github_pr(
        self,
        ticket_id: str,
        pr_url: str,
    ) -> None:
        """Attach a GitHub PR URL as a comment on the ticket."""
        mutation = """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
            }
        }
        """
        await self._query(mutation, {
            "input": {
                "issueId": ticket_id,
                "body": f"GitHub PR: {pr_url}",
            },
        })
        logger.info("Linked PR {} to ticket {}", pr_url, ticket_id)

    async def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Fetch ticket details."""
        query = """
        query Issue($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                state { name }
                priority
                url
                comments {
                    nodes {
                        body
                        createdAt
                    }
                }
            }
        }
        """
        data = await self._query(query, {"id": ticket_id})
        return data.get("issue", {})

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _ticket_description(self, question: Question) -> str:
        lines = [
            f"**Question ID**: `{question.id}`",
            f"**Type**: {question.question_type.value}",
            f"**Difficulty**: {question.difficulty.value}",
            f"**Domain**: {question.domain}",
            f"**Tags**: {', '.join(question.tags) or 'none'}",
            "",
            "### Question Stem",
            question.body,
        ]
        if question.choices:
            lines.append("")
            lines.append("### Choices")
            for c in question.choices:
                marker = "✅" if c.is_correct else "  "
                lines.append(f"{marker} **{c.label}**: {c.text}")
        if question.github_pr_url:
            lines.append("")
            lines.append(f"**GitHub PR**: {question.github_pr_url}")
        return "\n".join(lines)

    def _review_comment(self, review: Review) -> str:
        emoji = {"pass": "✅", "needs_revision": "⚠️", "fail": "❌"}
        lines = [
            f"## Review: {emoji.get(review.verdict, '❓')} {review.verdict.upper()}",
            f"**Score**: {review.overall_score}/10",
            f"**Model**: {review.reviewer_model}",
            "",
            "### Criterion Scores",
        ]
        for cs in review.criterion_scores:
            lines.append(f"- **{cs.criterion}**: {cs.score}/10 — {cs.feedback}")
        lines.append("")
        lines.append("### Summary")
        lines.append(review.summary)
        if review.suggestions:
            lines.append("")
            lines.append("### Suggestions")
            for s in review.suggestions:
                lines.append(f"- {s}")
        return "\n".join(lines)
