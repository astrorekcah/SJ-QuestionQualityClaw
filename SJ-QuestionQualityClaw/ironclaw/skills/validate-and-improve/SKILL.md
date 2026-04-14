---
name: validate-and-improve
version: "1.0.0"
description: Validate learner feedback on assessment questions and improve them via the IronClaw pipeline
activation:
  keywords:
    - "validate"
    - "feedback"
    - "improve"
    - "question"
    - "assessment"
    - "fix"
  tags:
    - "assessment"
    - "quality"
    - "feedback"
  max_context_tokens: 2000
---

# Skill: Validate & Improve

## When to Use
Primary skill — triggered when feedback arrives on a question.
Drives the complete workflow: validate → pipeline → PR → Linear.

## Quick Path (one call)
```python
reviewer = QuestionReviewer()
validation, revision = await reviewer.process_feedback(question, feedback)
```
This validates, then if valid, runs the full IronClaw pipeline automatically.

## Full Integration Path

### 1. Load + track
```python
ghub = GitHubQuestionClient()
question = ghub.get_question(file_path)

linear = LinearClient()
ticket_id = await linear.create_feedback_ticket(question, feedback)
```

### 2. Validate
```python
validation = await reviewer.validate_feedback(question, feedback)
await linear.post_validation(ticket_id, validation)
```
OpenRouter LLM analyzes the code in the question's language, checks if
the feedback is technically correct, and returns a structured verdict.

### 3. Route on verdict
```python
if validation.verdict in ("valid", "partially_valid"):
    # Run pipeline: classify → strategies → assemble
    revision = await reviewer.improve_question(question, feedback, validation)

    # Pipeline internally:
    #   classify_feedback → ["fix_code", "fix_answer"]
    #   execute fix_code → tools.update_code() + validate_step()
    #   execute fix_answer → tools.update_answer() + validate_step()
    #   assemble → changelog + validate_roundtrip + export

    # Create PR + update Linear
    pr_url = ghub.create_revision_pr(revision)
    await linear.post_revision(ticket_id, revision, pr_url=pr_url)
    await linear.update_state(ticket_id, QuestionState.UPDATED)

elif validation.requires_human_review:
    issue_url = ghub.create_feedback_issue(question, feedback, validation)
    await linear.post_escalation(ticket_id, f"See: {issue_url}")

else:  # invalid
    await linear.update_state(ticket_id, QuestionState.ACTIVE)
```

### 4. Export
```python
platform_json = QuestionReviewer.export_revision(revision)
# Exact platform format — upload directly
```

## Pipeline Strategy Skills
The `improve_question()` call runs `ImprovementPipeline` which invokes
these IronClaw skills in order:

1. **classify_feedback** → which strategies to apply
2. **fix_code** / **fix_answer** / **fix_stem** / **fix_choices** /
   **fix_scenario** / **fix_distractors** → targeted changes via tools
3. **assemble_and_export** → validate + changelog + PR + Linear

Each strategy gets a focused OpenRouter call (~500 tokens) instead of
one massive prompt. Cheaper and more precise.

## Changelog on the Revision
```python
revision.changelog.strategies_used    # ["fix_code", "fix_answer"]
revision.changelog.total_fields_changed  # 3
revision.changelog.summary  # {answer_changed: True, code_changed: True, ...}
revision.changelog.all_steps_valid  # True
```
