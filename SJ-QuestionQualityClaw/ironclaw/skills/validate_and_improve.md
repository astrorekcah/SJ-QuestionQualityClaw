# Skill: Validate Feedback & Improve Question

## When to Use
Use this skill when a human leaves feedback on an assessment question.
This is your primary skill — it drives the core workflow.

## End-to-End Pipeline

```python
reviewer = QuestionReviewer()
validation, revision = await reviewer.process_feedback(
    question, feedback, auto_improve=True
)
```

This runs validate → improve in one call. Use the individual methods
when you need more control.

## Step 1: Validate Feedback

```python
validation = await reviewer.validate_feedback(question, feedback)
```

### Input
- `question`: `AssessmentQuestion` loaded from platform JSON
- `feedback`: `FeedbackComment` with the human's comment text

### Output: `FeedbackValidation`
- `verdict`: valid | partially_valid | invalid | unclear
- `confidence`: 0.0–1.0
- `reasoning`: detailed technical analysis
- `affected_areas`: which parts of the question are affected
- `requires_human_review`: true if confidence < 0.7
- `suggested_action`: what to do next

### Decision Logic
```
if verdict == "valid" or "partially_valid":
    → proceed to improve_question()
if verdict == "invalid":
    → notify operator: "Feedback is incorrect because: {reasoning}"
if verdict == "unclear":
    → flag for human review
if requires_human_review:
    → escalate regardless of verdict
```

## Step 2: Improve Question

```python
revision = await reviewer.improve_question(question, feedback, validation)
```

### Input
- `question`: original AssessmentQuestion
- `feedback`: the FeedbackComment being addressed
- `validation`: the FeedbackValidation from step 1

### Output: `QuestionRevision`
- `original`: the unmodified question
- `revised`: improved AssessmentQuestion in exact platform format
- `changes_made`: list of what changed
- `rationale`: why these changes address the feedback

### Platform Format Guarantee
The revised question is automatically validated:
1. LLM returns complete question in platform JSON schema
2. Immutable fields enforced (path, parameters, typeId)
3. Round-trip validation: export → re-parse → structural check
4. Choice structure verified per typeId (start/end, code, choice)

### Export for Upload
```python
json_str = QuestionReviewer.export_revision(revision)
# → platform-ready JSON string, directly uploadable
```

## Handling Different Question Types

### mc-block
- Choices reference code line ranges (`start`, `end`)
- If code changes, line numbers in choices may need updating
- The LLM is instructed to preserve line count when possible

### mc-code
- Choices contain inline code snippets
- If `codeLine` exists, preserve it
- Code snippets in choices can be revised independently

### mc-line
- Choices reference single line numbers
- If code changes, line references may shift

## Example Feedback Scenarios

### "The correct answer is wrong"
→ validate_feedback checks the code against all choices
→ if valid: improve_question updates the answers array
→ changes_made: ["Changed correct answer from C to B"]

### "Choice A is also a valid answer"
→ validate_feedback analyzes if A is technically defensible
→ if valid: improve_question may revise choices to differentiate
→ changes_made: ["Revised choice A to be clearly incorrect by..."]

### "The code has a syntax error on line 42"
→ validate_feedback checks the syntax
→ if valid: improve_question fixes the code
→ changes_made: ["Fixed syntax error on line 42: ..."]

### "The scenario is unrealistic"
→ validate_feedback assesses scenario plausibility
→ if valid: improve_question revises the stem
→ changes_made: ["Revised scenario to reflect real-world..."]

## Error Handling
- LLM returns no `revised_question` → fall back to original
- Round-trip validation fails → raise ValueError with details
- Low confidence → set `requires_human_review = true`
