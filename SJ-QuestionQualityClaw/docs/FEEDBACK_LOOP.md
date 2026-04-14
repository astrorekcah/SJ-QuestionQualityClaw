# Feedback Loop Workflow

Complete guide to how SJ-QuestionQualityClaw processes feedback on assessment questions — from input to platform-ready output.

## Overview

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│  Question    │     │   Feedback   │     │  Validation    │     │  Improved    │
│  (JSON file) │ ──→ │  (comment)   │ ──→ │  (LLM check)  │ ──→ │  Question    │
└─────────────┘     └──────────────┘     └────────────────┘     │  (JSON file) │
                                                                 └──────────────┘
                                              │
                                              ↓ if invalid
                                         ┌──────────┐
                                         │ Rejected  │
                                         │ (reason)  │
                                         └──────────┘
```

## Step-by-Step

### 1. Input: Question + Feedback

**Question**: A JSON file in the platform format (mc-block, mc-code, mc-line, or mc-generic).
Drop it into `questions/` or provide the file path.

**Feedback**: A text comment from a learner, reviewer, or SME. Examples:
- "The correct answer should be D, not C"
- "Line 42 has a syntax error"
- "Choice A is also a valid answer"
- "The scenario is unrealistic"

**CLI**:
```bash
python scripts/run.py process questions/example.json "The answer should be D"
```

**Python**:
```python
from sjqqc.models import AssessmentQuestion, FeedbackComment
from sjqqc.reviewer import QuestionReviewer

question = AssessmentQuestion(**json.load(open("question.json")))
feedback = FeedbackComment(question_path=question.path, comment="...")
reviewer = QuestionReviewer()
```

### 2. Validate Feedback

The system determines if the feedback is **technically correct** before making any changes.

```python
validation = await reviewer.validate_feedback(question, feedback)
```

The LLM receives:
- The full question (stem, code, choices, correct answer)
- The quality baseline for this question type (12 dimensions)
- The feedback comment

It returns:
- **verdict**: `valid` | `partially_valid` | `invalid` | `unclear`
- **confidence**: 0.0–1.0
- **reasoning**: detailed technical analysis
- **suggested_action**: what to do next
- **requires_human_review**: true if confidence < 0.7

**Decision routing**:
| Verdict | Action |
|---------|--------|
| `valid` | Proceed to improvement pipeline |
| `partially_valid` | Proceed (feedback has merit but may be imprecise) |
| `invalid` | Stop — feedback is wrong. Return reasoning. |
| `unclear` | Escalate for human review |

### 3. Classify Feedback → Pick Strategies

If feedback is valid, the pipeline classifies it to determine which fix strategies to apply.

```python
# Inside ImprovementPipeline.run():
strategies = await self.classify(question, feedback)
# → ["fix_code", "fix_answer"]
```

Available strategies:
| Strategy | What it fixes | Allowed fields |
|----------|---------------|----------------|
| `fix_code` | Syntax errors, logic flaws | code lines, choice references |
| `fix_answer` | Wrong correct answer | answers array |
| `fix_stem` | Unclear question text | stem text |
| `fix_choices` | Choice content issues | choice content |
| `fix_scenario` | Unrealistic scenario | stem scenario portion |
| `fix_distractors` | Weak wrong choices | non-correct choices |

**Execution order matters**:
1. `fix_code` first (code changes may shift line references)
2. `fix_answer` second (highest priority)
3. `fix_choices` third (may depend on code)
4. `fix_stem` / `fix_scenario` / `fix_distractors` last

### 4. Execute Each Strategy

Each strategy gets a **focused LLM call** (~500 tokens) scoped to its allowed fields.
The LLM decides *what* to change. Tools apply the change atomically.

```python
current, step = await self.execute_strategy("fix_answer", question, original, feedback)
# Internally:
#   LLM returns: {"new_answer": "d", "reason": "..."}
#   tools.update_answer(question, "d") → (updated_question, FieldChange)
#   tools.validate_step(original, updated) → StepValidation
```

After each step:
- `validate_step()` checks structural integrity (same typeId, same choice keys, valid answer)
- If validation fails, the pipeline **stops** and reports which step broke
- Every change produces a `FieldChange` record for the audit trail

### 5. Assemble + Validate + Export

```python
changelog, platform_json = self.assemble(original, revised, steps, feedback)
```

This final step:
1. Builds the `ImprovementChangelog` from all pipeline steps
2. Runs `validate_roundtrip()`: export → re-parse → structural check
3. Exports platform-exact JSON via `export_platform_json()`

The changelog tracks:
- Which strategy skills were used
- Every field that changed (path, old value, new value, reason)
- Whether each step passed validation
- Summary: `{answer_changed, code_changed, choices_changed, stem_changed}`

### 6. Output

The revised question is available as:
- **Platform JSON string** — `QuestionReviewer.export_revision(revision)` — directly uploadable
- **QuestionRevision object** — includes original, revised, changelog, changes_made, rationale
- **File** — CLI writes to `<question_id>_revised.json`

## Format Preservation Rules

Every revised question must pass these checks:

| Check | Enforced by |
|-------|-------------|
| Same `path` | Immutable — pipeline cannot change it |
| Same `parameters` | Immutable |
| Same `typeId` | Immutable |
| Same choice keys (a, b, c, d) | `validate_step()` |
| Correct choice structure per typeId | `_validate_choice_structure()` |
| Non-empty answers array | `validate_step()` |
| Answer key exists in choices | `validate_step()` |
| Non-empty code (except mc-generic) | `validate_step()` |
| Export → re-parse produces identical JSON | `validate_roundtrip()` |

## Quality Baseline

Every LLM call includes the quality baseline for the question's type.
The baseline defines 12 dimensions with pass/fail criteria:

**Critical (must fix)**:
- answer_correctness — is the answer right?
- single_correct_answer — exactly one correct?
- domain_accuracy — technically accurate?
- vulnerability_presence — vulnerability is where the answer says?
- choice_line_accuracy — line references correct?

**Major (should fix)**:
- stem_clarity — question is clear?
- distractor_plausibility — wrong choices are plausible?
- code_syntactic_validity — code compiles?
- code_choice_quality / generic_choice_quality

**Minor (nice to fix)**:
- scenario_realism — scenario is plausible?
- code_realism — code looks production-like?

## Integration Points

### GitHub
- Read questions from `sj-question-bank` repo
- Create PRs with revised questions + changelog in PR body
- Create issues for human-review escalations

### Linear
- Create ticket when feedback arrives
- Post validation results as comments
- Post revision changelog + PR link
- Update ticket state through pipeline

### Database (PostgreSQL)
- Tables: questions, feedback, validations, revisions, audit_trail
- Full history of every feedback cycle

## Error Handling

| Scenario | Behavior |
|----------|----------|
| LLM returns non-JSON | Fallback: extract first `{...}` block from text |
| Strategy changes wrong field | `validate_step()` catches it, pipeline stops |
| Round-trip fails | `ValueError` with specific structural problems |
| All pipeline steps fail | Return original question unchanged |
| Low confidence (< 0.7) | Flag `requires_human_review`, escalate |
| Linear not configured | Graceful skip with warning log |
| GitHub not configured | Graceful skip with warning log |

## Running the Full Loop

```bash
# 1. Assess current quality
python scripts/run.py assess

# 2. Process feedback on one question
python scripts/run.py process questions/file.json "The answer is wrong because..."

# 3. Check the output
cat file_revised.json | python -m json.tool

# 4. Interactive demo
python scripts/demo.py
```
