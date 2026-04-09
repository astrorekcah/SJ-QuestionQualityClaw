"""GitHub integration for assessment questions.

Questions are stored as platform JSON files in a GitHub repo, organized by
their path field. The client reads questions, creates PRs for revisions,
and opens issues for quality flags.

Typical flow:
  1. Read question from repo by path
  2. Pipeline processes feedback → produces revision
  3. Create PR with the revised platform JSON
  4. Link PR to Linear ticket
"""

from __future__ import annotations

import json
import os

from github import Auth, Github, GithubException
from loguru import logger

from sjqqc.models import (
    AssessmentQuestion,
    FeedbackComment,
    FeedbackValidation,
    QuestionRevision,
)
from sjqqc.tools import export_platform_json


class GitHubQuestionClient:
    """Read/write assessment questions in a GitHub repository.

    Questions are stored as platform JSON files at their path:
      `questions/<path-segments>/<question_id>.json`
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        repo_owner: str | None = None,
        repo_name: str | None = None,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo_owner = repo_owner or os.environ.get(
            "GITHUB_REPO_OWNER", "astrorekcah"
        )
        self.repo_name = repo_name or os.environ.get(
            "GITHUB_REPO_NAME", "sj-question-bank"
        )
        self._gh: Github | None = None

    @property
    def gh(self) -> Github:
        if self._gh is None:
            self._gh = Github(auth=Auth.Token(self.token))
        return self._gh

    @property
    def repo(self):
        return self.gh.get_repo(f"{self.repo_owner}/{self.repo_name}")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_question(self, file_path: str) -> AssessmentQuestion | None:
        """Fetch a question from the repo by file path."""
        try:
            contents = self.repo.get_contents(file_path)
            data = json.loads(contents.decoded_content.decode())
            return AssessmentQuestion(**data)
        except GithubException as exc:
            if exc.status == 404:
                logger.debug("Question not found at {}", file_path)
                return None
            raise

    def list_questions(self, directory: str = "questions") -> list[AssessmentQuestion]:
        """Recursively list all question JSON files under a directory."""
        questions: list[AssessmentQuestion] = []
        try:
            self._walk_dir(directory, questions)
        except GithubException as exc:
            if exc.status == 404:
                logger.info("Directory '{}' not found", directory)
            else:
                raise
        return questions

    def _walk_dir(
        self, path: str, out: list[AssessmentQuestion]
    ) -> None:
        contents = self.repo.get_contents(path)
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            if item.type == "dir":
                self._walk_dir(item.path, out)
            elif item.name.endswith(".json"):
                try:
                    data = json.loads(item.decoded_content.decode())
                    out.append(AssessmentQuestion(**data))
                except Exception as exc:
                    logger.warning(
                        "Failed to parse {}: {}", item.path, exc
                    )

    # ------------------------------------------------------------------
    # Write (via PRs)
    # ------------------------------------------------------------------

    def create_revision_pr(
        self,
        revision: QuestionRevision,
        *,
        base_branch: str = "main",
    ) -> str:
        """Create a PR with the revised question in platform JSON format.

        Returns the PR URL.
        """
        q = revision.revised
        qid = q.question_id
        branch_name = f"fix/{qid}"
        file_path = f"questions/{q.path}.json"
        content = export_platform_json(q)

        # Create branch
        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        try:
            self.repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_ref.object.sha,
            )
        except GithubException as exc:
            if exc.status != 422:  # 422 = already exists
                raise
            logger.info("Branch {} already exists", branch_name)

        # Create or update file
        try:
            existing = self.repo.get_contents(file_path, ref=branch_name)
            self.repo.update_file(
                file_path,
                message=self._commit_message(revision),
                content=content,
                sha=existing.sha,
                branch=branch_name,
            )
        except GithubException:
            self.repo.create_file(
                file_path,
                message=self._commit_message(revision),
                content=content,
                branch=branch_name,
            )

        pr = self.repo.create_pull(
            title=f"[Fix] {q.title}",
            body=self._pr_body(revision),
            head=branch_name,
            base=base_branch,
        )

        logger.info("Created PR #{} for {}", pr.number, qid)
        return pr.html_url

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def create_feedback_issue(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
        validation: FeedbackValidation,
    ) -> str:
        """Open a GitHub issue for feedback that needs human review.

        Returns the issue URL.
        """
        issue = self.repo.create_issue(
            title=f"[Review] {question.title}",
            body=self._issue_body(question, feedback, validation),
            labels=["feedback-review", question.language],
        )
        logger.info("Created issue #{} for {}", issue.number, question.question_id)
        return issue.html_url

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _commit_message(self, revision: QuestionRevision) -> str:
        changes = "; ".join(revision.changes_made[:3])
        return f"fix({revision.revised.question_id}): {changes}"

    def _pr_body(self, revision: QuestionRevision) -> str:
        q = revision.revised
        cl = revision.changelog
        lines = [
            f"## Question Revision: {q.title}",
            f"**Path**: `{q.path}`",
            f"**Language**: {q.language}",
            f"**Type**: {q.prompt.typeId}",
            "",
            "### Feedback",
            f"> {revision.feedback_id}",
            "",
            "### Changes",
        ]
        for change in revision.changes_made:
            lines.append(f"- {change}")
        lines.append(f"\n**Rationale**: {revision.rationale}")

        if cl:
            lines.append("\n### Changelog Summary")
            summary = cl.summary
            for area, changed in summary.items():
                lines.append(
                    f"- {area}: {'changed' if changed else 'unchanged'}"
                )
            lines.append(f"- Strategies: {', '.join(cl.strategies_used)}")
            lines.append(f"- Fields changed: {cl.total_fields_changed}")

        lines.append("\n---\n*Generated by SJ-QuestionQualityClaw*")
        return "\n".join(lines)

    def _issue_body(
        self,
        question: AssessmentQuestion,
        feedback: FeedbackComment,
        validation: FeedbackValidation,
    ) -> str:
        return "\n".join([
            f"## Feedback Review: {question.title}",
            f"**Path**: `{question.path}`",
            f"**Language**: {question.language}",
            f"**Answer**: {question.correct_answer_key}",
            "",
            "### Feedback",
            f"> {feedback.comment}",
            f"**Author**: {feedback.author}",
            "",
            "### Validation",
            f"**Verdict**: {validation.verdict}",
            f"**Confidence**: {validation.confidence:.0%}",
            f"**Reasoning**: {validation.reasoning}",
            f"**Requires human review**: {validation.requires_human_review}",
            "",
            "---",
            "*Created by SJ-QuestionQualityClaw*",
        ])

    def close(self) -> None:
        if self._gh:
            self._gh.close()
            self._gh = None
