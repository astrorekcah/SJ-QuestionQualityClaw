"""GitHub integration — manage questions as structured files in a repo."""

from __future__ import annotations

import contextlib
import json
import os

from github import Auth, Github, GithubException
from loguru import logger

from sjqqc.models import Question


class GitHubQuestionClient:
    """Read/write assessment questions in a GitHub repository.

    Questions are stored as JSON files under `questions/<domain>/<id>.json`.
    Changes go through PRs for review tracking.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        repo_owner: str | None = None,
        repo_name: str | None = None,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = repo_owner or os.environ.get("GITHUB_REPO_OWNER", "astrorekcah")
        self.repo_name = repo_name or os.environ.get("GITHUB_REPO_NAME", "sj-question-bank")
        self._gh: Github | None = None

    @property
    def gh(self) -> Github:
        if self._gh is None:
            self._gh = Github(auth=Auth.Token(self.token))
        return self._gh

    @property
    def repo(self):
        return self.gh.get_repo(f"{self.repo_owner}/{self.repo_name}")

    def _question_path(self, question: Question) -> str:
        """Compute the file path for a question in the repo."""
        return f"questions/{question.domain}/{question.id}.json"

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_question(self, question_id: str, domain: str = "general") -> Question | None:
        """Fetch a question from the repo by ID."""
        path = f"questions/{domain}/{question_id}.json"
        try:
            contents = self.repo.get_contents(path)
            data = json.loads(contents.decoded_content.decode())
            return Question(**data)
        except GithubException as exc:
            if exc.status == 404:
                logger.debug("Question {} not found at {}", question_id, path)
                return None
            raise

    def list_questions(self, domain: str = "general") -> list[Question]:
        """List all questions in a domain directory."""
        questions: list[Question] = []
        try:
            contents = self.repo.get_contents(f"questions/{domain}")
            for item in contents:
                if item.name.endswith(".json"):
                    data = json.loads(item.decoded_content.decode())
                    questions.append(Question(**data))
        except GithubException as exc:
            if exc.status == 404:
                logger.info("No questions directory for domain '{}'", domain)
                return []
            raise
        return questions

    def list_domains(self) -> list[str]:
        """List all domain directories in the questions folder."""
        try:
            contents = self.repo.get_contents("questions")
            return [item.name for item in contents if item.type == "dir"]
        except GithubException:
            return []

    # ------------------------------------------------------------------
    # Write operations (via PRs)
    # ------------------------------------------------------------------

    def create_question_pr(
        self,
        question: Question,
        *,
        base_branch: str = "main",
    ) -> str:
        """Create a PR to add a new question to the repo.

        Returns the PR URL.
        """
        branch_name = f"question/{question.id}"
        file_path = self._question_path(question)
        content = question.model_dump_json(indent=2)

        # Create branch from base
        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        try:
            self.repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_ref.object.sha,
            )
        except GithubException as exc:
            if exc.status == 422:  # Branch already exists
                logger.warning("Branch {} already exists, updating", branch_name)
            else:
                raise

        # Create or update file on branch
        try:
            existing = self.repo.get_contents(file_path, ref=branch_name)
            self.repo.update_file(
                file_path,
                message=f"Update question: {question.title}",
                content=content,
                sha=existing.sha,
                branch=branch_name,
            )
        except GithubException:
            self.repo.create_file(
                file_path,
                message=f"Add question: {question.title}",
                content=content,
                branch=branch_name,
            )

        # Create PR
        pr = self.repo.create_pull(
            title=f"[Question] {question.title}",
            body=self._pr_body(question),
            head=branch_name,
            base=base_branch,
        )

        logger.info("Created PR #{} for question {}", pr.number, question.id)
        return pr.html_url

    def update_question_pr(
        self,
        question: Question,
        *,
        base_branch: str = "main",
    ) -> str:
        """Create a PR to update an existing question.

        Returns the PR URL.
        """
        branch_name = f"question/{question.id}-update"
        file_path = self._question_path(question)
        content = question.model_dump_json(indent=2)

        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        with contextlib.suppress(GithubException):
            self.repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_ref.object.sha,
            )

        existing = self.repo.get_contents(file_path, ref=branch_name)
        self.repo.update_file(
            file_path,
            message=f"Revise question: {question.title}",
            content=content,
            sha=existing.sha,
            branch=branch_name,
        )

        pr = self.repo.create_pull(
            title=f"[Revision] {question.title}",
            body=self._pr_body(question, is_revision=True),
            head=branch_name,
            base=base_branch,
        )

        logger.info("Created revision PR #{} for question {}", pr.number, question.id)
        return pr.html_url

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def create_quality_issue(
        self,
        question: Question,
        issues: list[str],
    ) -> str:
        """Open a GitHub issue for quality problems on a question.

        Returns the issue URL.
        """
        body_lines = [
            f"## Quality Issues: {question.title}",
            f"**Question ID**: `{question.id}`",
            f"**Domain**: {question.domain}",
            f"**State**: {question.state}",
            "",
            "### Issues Found",
        ]
        for issue in issues:
            body_lines.append(f"- {issue}")

        issue = self.repo.create_issue(
            title=f"[Quality] {question.title}",
            body="\n".join(body_lines),
            labels=["quality-review", question.domain],
        )

        logger.info("Created quality issue #{} for question {}", issue.number, question.id)
        return issue.html_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pr_body(self, question: Question, *, is_revision: bool = False) -> str:
        action = "Revision of" if is_revision else "New"
        return "\n".join([
            f"## {action} Assessment Question",
            "",
            f"**Title**: {question.title}",
            f"**Type**: {question.question_type.value}",
            f"**Difficulty**: {question.difficulty.value}",
            f"**Domain**: {question.domain}",
            f"**Tags**: {', '.join(question.tags) or 'none'}",
            "",
            "### Question",
            question.body,
            "",
            "---",
            "*Created by SJ-QuestionQualityClaw*",
        ])

    def close(self) -> None:
        """Close the GitHub connection."""
        if self._gh:
            self._gh.close()
            self._gh = None
