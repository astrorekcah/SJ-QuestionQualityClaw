---
name: manage-lifecycle
version: "1.0.0"
description: Orchestrate the full feedback cycle with GitHub PRs and Linear tickets
activation:
  keywords:
    - "lifecycle"
    - "github"
    - "linear"
    - "PR"
    - "ticket"
  tags:
    - "assessment"
    - "integration"
    - "lifecycle"
  max_context_tokens: 1500
---

# Skill: Manage Lifecycle

## When to Use
Use this skill to run the complete feedback cycle with GitHub and Linear
integration. This is the end-to-end orchestration skill.

## Full Cycle

```
1. Read question from GitHub
2. Create Linear ticket for feedback
3. Validate feedback (OpenRouter)
4. Post validation to Linear
5. If valid: run pipeline (classify → fix strategies → assemble)
6. Create GitHub PR with revised question
7. Post revision + PR link to Linear
8. Update Linear ticket state → Done
```

## Step-by-Step

### 1. Load question
```python
ghub = GitHubQuestionClient()
question = ghub.get_question("questions/path/to/question.json")
```
If the question path is known from feedback context, use it directly.
For batch operations, use `ghub.list_questions("questions/secure-coding")`.

### 2. Create Linear ticket
```python
linear = LinearClient()
ticket_id = await linear.create_feedback_ticket(question, feedback)
```
Ticket starts in **Triage** state with question details + feedback text.

### 3. Validate feedback
```python
reviewer = QuestionReviewer()
validation = await reviewer.validate_feedback(question, feedback)
await linear.post_validation(ticket_id, validation)
```
Linear gets a comment with: verdict, confidence, reasoning, suggested action.

### 4. Decision routing
```
if validation.verdict in ("valid", "partially_valid"):
    → proceed to improvement pipeline
    → Linear state: UNDER_REVIEW

if validation.verdict == "invalid":
    → no changes
    → Linear comment: "Feedback is incorrect: {reasoning}"
    → Linear state: ACTIVE (back to normal)

if validation.requires_human_review:
    → create GitHub issue for human review
    → Linear comment: "Escalated for human review"
    → Linear state: UNDER_REVIEW (await human)
```

### 5. Run pipeline + create PR
```python
revision = await reviewer.improve_question(question, feedback, validation)
pr_url = ghub.create_revision_pr(revision)
await linear.post_revision(ticket_id, revision, pr_url=pr_url)
await linear.update_state(ticket_id, QuestionState.UPDATED)
```
The PR contains:
- Revised question in exact platform JSON format
- Changelog summary (strategies used, fields changed)
- Link back to the Linear ticket

### 6. Export for upload
```python
json_str = QuestionReviewer.export_revision(revision)
# This string is the exact platform format — upload directly
```

## Escalation Path
When `validation.requires_human_review` is true:
```python
issue_url = ghub.create_feedback_issue(question, feedback, validation)
await linear.post_escalation(ticket_id, f"See: {issue_url}")
```

## Batch Processing
```python
questions = ghub.list_questions("questions/secure-coding/ruby")
for q in questions:
    result = await reviewer.quality_check(q)
    # result has overall_score, issues_found, verdict
```
