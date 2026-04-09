# Skill: Manage Question Lifecycle

## When to Use
Use this skill to orchestrate state transitions through the review pipeline.
This skill ties together the reviewer engine, GitHub client, and Linear client
into end-to-end workflows.

## Lifecycle State Machine
```
draft ──→ review ──┬──→ approved ──→ published
              │
              ├──→ revision ──→ review (loop, max 3 cycles)
              │
              └──→ rejected
```

Max revision cycles: 3. If a question hasn't passed after 3 revision rounds,
it transitions to `rejected` with accumulated feedback.

## Operations

### 1. Submit Question
Trigger: new question arrives (via channel command, API, or file upload)

```python
# Validate
question = Question(**raw_data)  # Pydantic validation

# GitHub: create PR
ghub = GitHubQuestionClient()
pr_url = ghub.create_question_pr(question)
question.github_pr_url = pr_url

# Linear: create ticket
linear = LinearClient()
ticket_id = await linear.create_ticket(question)
question.linear_ticket_id = ticket_id

# Link PR to ticket
await linear.link_github_pr(ticket_id, pr_url)
```

Channel response: "Submitted `{question.id}` — PR: {pr_url}, Ticket: {ticket_id}"

### 2. Trigger Review
Trigger: operator command `/review <id>` or automatic on submission

```python
# Update state
question.state = QuestionState.REVIEW
await linear.update_ticket_state(ticket_id, QuestionState.REVIEW)

# Run multi-pass review (minimum 2 passes for approval pipeline)
reviewer = QuestionReviewer()
feedback = await reviewer.multi_pass(question, passes=3)

# Post review to Linear
for review in feedback.reviews:
    await linear.add_review_comment(ticket_id, review)

# Route based on verdict
if feedback.consensus_verdict == ReviewVerdict.PASS:
    question.state = QuestionState.APPROVED
    await linear.update_ticket_state(ticket_id, QuestionState.APPROVED)
    # Channel: "✅ PASS (7.8/10) — ready for approval"

elif feedback.consensus_verdict == ReviewVerdict.NEEDS_REVISION:
    question.state = QuestionState.REVISION
    await linear.update_ticket_state(ticket_id, QuestionState.REVISION)
    ghub.create_quality_issue(question, feedback.key_issues)
    # Channel: "⚠️ NEEDS_REVISION (5.9/10) — 3 issues to address"

else:  # FAIL
    question.state = QuestionState.REJECTED
    await linear.update_ticket_state(ticket_id, QuestionState.REJECTED)
    # Channel: "❌ FAIL (3.2/10) — fundamental problems"
```

If disputed criteria detected, append: "⚠️ Disputed: {criteria} — human review recommended"

### 3. Apply Revision
Trigger: author submits revised question, or auto-revision from `reviewer.revise()`

```python
# Option A: Author submits revision manually
revised_question = Question(**revised_data)

# Option B: Auto-revise from feedback
latest_review = feedback.reviews[0]  # Use highest-confidence pass
revised_question = await reviewer.revise(question, latest_review)

# Create update PR
pr_url = ghub.update_question_pr(revised_question)
await linear.link_github_pr(ticket_id, pr_url)

# Run comparative review
comparison = await reviewer.compare(question, revised_question, latest_review)
await linear.add_review_comment(ticket_id, comparison.revised_review)

if comparison.revision_adequate:
    # Re-enter review with the revised version
    # (triggers step 2 again with the revised question)
    pass
else:
    # Channel: "Revision didn't address: {comparison.unresolved_issues}"
    pass
```

### 4. Approve & Publish
Trigger: operator command `/approve <id>` after PASS verdict

Pre-conditions (enforced):
- consensus_verdict == PASS
- ≥2 review passes completed
- No disputed criteria on `correctness`
- score ≥ 7.0

```python
# Verify pre-conditions
assert feedback.consensus_verdict == ReviewVerdict.PASS
assert len(feedback.reviews) >= 2
assert "correctness" not in feedback.disputed_criteria
assert feedback.average_score >= 7.0

# Publish
question.state = QuestionState.PUBLISHED
await linear.update_ticket_state(ticket_id, QuestionState.PUBLISHED)
# Channel: "✅ Published question {question.id}"
```

### 5. Reject
Trigger: operator command `/reject <id> <reason>` or FAIL verdict

```python
question.state = QuestionState.REJECTED
await linear.update_ticket_state(ticket_id, QuestionState.REJECTED)
# Channel: "❌ Rejected: {reason}"
```

## Audit Trail

Every operation appends to `RevisionHistory`:
- Version number
- Question snapshot (full state at that point)
- Review results
- Comparison result (if revision)
- Timestamp

Access via `history.score_trajectory` to see improvement over revision cycles.

## Channel Commands

| Command | Operation | Notes |
|---------|-----------|-------|
| `/submit <json>` | Submit Question | Validates, creates PR + ticket |
| `/review <id>` | Trigger Review | Multi-pass, updates ticket |
| `/feedback <id>` | Show Feedback | Latest review scores + suggestions |
| `/revise <id>` | Auto-Revision | Generates improved version |
| `/compare <id>` | Comparative Review | After revision, shows diff |
| `/approve <id>` | Approve & Publish | Enforces pre-conditions |
| `/reject <id> <reason>` | Reject | With reason, closes ticket |
| `/status` | Pipeline Status | Counts by state across all questions |
| `/audit <id>` | Revision History | Full audit trail for a question |
| `/batch <domain>` | Batch Review | Review all questions in a domain |
