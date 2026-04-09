# Skill: Assemble & Export

## When to Use
Final step after strategy skills have run. Validates the final question,
builds the changelog, exports platform JSON, creates a GitHub PR, and
updates the Linear ticket.

## Process

### 1. Build changelog
```python
from sjqqc.changelog import build_changelog
changelog = build_changelog(original, revised, steps=pipeline_steps, feedback_id=feedback.id)
```
The changelog contains:
- Every field change with old/new values
- Which strategy skill made each change
- Per-step validation status
- Summary: `{answer_changed, code_changed, choices_changed, stem_changed}`

### 2. Validate round-trip
```python
from sjqqc.tools import validate_roundtrip
validate_roundtrip(original, revised)  # raises ValueError on failure
```
This ensures the revised question:
- Exports to valid platform JSON
- Re-parses without error
- Has same typeId, same choice keys, valid answer reference

### 3. Export platform JSON
```python
from sjqqc.tools import export_platform_json
json_str = export_platform_json(revised)
# This string is directly uploadable to the external platform
```

### 4. Create GitHub PR
```python
ghub = GitHubQuestionClient()
pr_url = ghub.create_revision_pr(revision)
```
PR includes: question path, language, changes list, changelog summary.

### 5. Update Linear
```python
linear = LinearClient()
await linear.post_revision(ticket_id, revision, pr_url=pr_url)
await linear.update_state(ticket_id, QuestionState.UPDATED)
```
Linear ticket gets: changelog summary, strategies used, PR link, state → Done.

## Validation Checks
- Round-trip: export → re-parse succeeds
- Structural: same typeId, same choice keys, valid answer reference
- All pipeline steps passed validation
- If any step failed: STOP, report errors, don't create PR

## If Validation Fails
```python
if not changelog.all_steps_valid:
    # Don't export, don't PR
    failed_steps = [s for s in changelog.steps if not s.validation.passed]
    errors = [e for s in failed_steps for e in s.validation.errors]
    # Report to operator + Linear
```
