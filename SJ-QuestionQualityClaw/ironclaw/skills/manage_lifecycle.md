# Skill: Manage Question Lifecycle

## When to Use
Use this skill to orchestrate the full feedback → validation → revision
pipeline with GitHub and Linear integration.

## Lifecycle State Machine
```
active ──→ feedback_received ──→ under_review ──→ updated
                                      │
                                      ├──→ revision ──→ under_review (loop)
                                      │
                                      └──→ rejected (feedback invalid)
```

## Operations

### 1. Receive Feedback
Trigger: human comment arrives on a question

```python
question = AssessmentQuestion(**json.load(open("question.json")))
feedback = FeedbackComment(
    question_path=question.path,
    comment="The correct answer should be B, not C",
    author="reviewer-name",
)
question.state = QuestionState.FEEDBACK_RECEIVED
```

### 2. Process Feedback (validate + improve)
```python
reviewer = QuestionReviewer()
validation, revision = await reviewer.process_feedback(question, feedback)

question.state = QuestionState.UNDER_REVIEW

if validation.verdict in ("valid", "partially_valid") and revision:
    # Export platform-ready JSON
    updated_json = QuestionReviewer.export_revision(revision)

    # GitHub: create PR with revised question
    ghub = GitHubQuestionClient()
    pr_url = ghub.update_question_pr(revision.revised)

    # Linear: update ticket + post results
    linear = LinearClient()
    await linear.update_ticket_state(ticket_id, QuestionState.UPDATED)

    question.state = QuestionState.UPDATED

elif validation.requires_human_review:
    # Escalate — don't auto-modify
    question.state = QuestionState.UNDER_REVIEW

else:
    # Feedback is invalid — no changes
    question.state = QuestionState.ACTIVE
```

### 3. Export Updated Question
```python
# The revised question in exact platform format
json_str = QuestionReviewer.export_revision(revision)

# Write to file (same format as original, uploadable as-is)
with open("updated_question.json", "w") as f:
    f.write(json_str)
```

### 4. Quality Audit (batch)
```python
questions = [AssessmentQuestion(**json.load(open(f))) for f in files]
results = [await reviewer.quality_check(q) for q in questions]
```

## Audit Trail
Every operation appends to `QuestionAuditTrail`:
- `feedback_received` — when comment arrives
- `validation_complete` — verdict + confidence
- `revision_created` — changes made
- `human_review_requested` — when escalated
- `question_updated` — when uploaded back
