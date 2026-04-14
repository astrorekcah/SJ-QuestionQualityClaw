# Next Steps & Customization Guide

How to get your question files and learner feedback into the system and start processing.

## Step 1: Get Your Question Files

### Format

Every question must be a JSON file matching the platform schema. Four types are supported:

```json
{
  "path": "secure-coding/category/subcategory/question-id",
  "title": "(Language) Category | Subcategory",
  "parameters": {"programmingLanguage": ["python"]},
  "prompt": {
    "typeId": "mc-block",
    "configuration": {
      "prompt": "Scenario text asking the learner to identify something...",
      "code": ["line 0", "line 1", "..."],
      "choices": [
        {"key": "a", "start": 10, "end": 15},
        {"key": "b", "start": 20, "end": 25},
        {"key": "c", "start": 30, "end": 35},
        {"key": "d", "start": 40, "end": 45}
      ]
    }
  },
  "answers": [{"value": "c"}]
}
```

**Choice format varies by typeId:**
- `mc-block`: `{"key": "a", "start": N, "end": N}` — line ranges
- `mc-code`: `{"key": "a", "code": ["line1", "line2"]}` — code snippets
- `mc-line`: `{"key": "a", "choice": N}` — single line number
- `mc-generic`: `{"key": "a", "choice": "text answer"}` — text

### Where to put them

Drop JSON files into the `questions/` directory:

```bash
cp /path/to/your/questions/*.json questions/
```

Verify they load:
```bash
python scripts/run.py assess
```

This runs instant structural checks on every file — you'll see which ones pass and which have format issues.

## Step 2: Get Your Feedback

### Option A: Feedback files (batch processing)

Create a feedback file alongside each question. Two formats:

**Structured (`.feedback.json`):**
```json
{
  "comment": "The correct answer should be B — the function on line 42 is actually safe because it uses parameterized queries",
  "author": "security-reviewer",
  "target_choice": "c",
  "target_lines": [40, 45]
}
```

**Plain text (`.feedback.txt`):**
```
The correct answer should be B — the function on line 42 is actually safe because it uses parameterized queries
```

**Naming convention** — feedback file must share the question file's name:
```
questions/python_sqli.json              ← question
questions/python_sqli.feedback.json     ← feedback (structured)
questions/python_sqli.feedback.txt      ← or feedback (plain text)
```

Then process all paired questions:
```bash
python scripts/test_e2e.py --live
```

### Option B: CLI (one at a time)

```bash
python scripts/run.py process questions/python_sqli.json "The answer should be B because line 42 uses parameterized queries"
```

### Option C: Telegram bot (interactive)

```bash
# Set bot token in .env first
python scripts/run.py telegram
```

Then message your bot:
```
/feedback python_sqli The answer should be B because line 42 uses parameterized queries
```

### Option D: Spreadsheet / CSV export

If your feedback is in a spreadsheet, export it to JSON:

```python
import json, csv

with open("feedback.csv") as f:
    for row in csv.DictReader(f):
        # Expects columns: question_id, comment, author
        feedback = {
            "comment": row["comment"],
            "author": row.get("author", "reviewer"),
        }
        filename = f"questions/{row['question_id']}.feedback.json"
        with open(filename, "w") as out:
            json.dump(feedback, out, indent=2)
```

## Step 3: Process Everything

### Quick: assess first, then process

```bash
# 1. Check structural quality of all questions
python scripts/run.py assess

# 2. Process all questions that have feedback files
python scripts/test_e2e.py --live

# 3. Or process a specific question
python scripts/run.py process questions/file.json "feedback text"
```

### Batch: process all questions with the same feedback

```bash
python scripts/run.py batch-process "Is the marked correct answer actually correct?"
```

This runs the full pipeline on every question in `questions/` — useful for a first-pass quality audit.

## Step 4: Review Outputs

Revised questions are written to `questions/<id>_revised.json` in the exact platform format. Compare original vs revised:

```bash
# Quick diff
diff <(python -m json.tool questions/original.json) <(python -m json.tool questions/original_revised.json)

# Or use the changelog from the pipeline output
```

To upload back to the platform:
```bash
# The _revised.json file IS the platform format — upload directly
cat questions/sc-aa-Ruby-863-2-v2_revised.json
```

## Customization

### Change the LLM model

Edit `.env`:
```
SELECTED_MODEL=anthropic/claude-sonnet-4.5
```

Or use a cheaper model for batch operations:
```
SELECTED_MODEL=openai/gpt-4o-mini
```

### Adjust quality thresholds

Edit `config/quality_baseline.py`. Each dimension has a `pass_threshold`:

```python
ANSWER_CORRECTNESS = QualityDimension(
    name="answer_correctness",
    pass_threshold=8,  # Change this to be stricter (9) or looser (6)
    ...
)
```

### Add a new quality dimension

Add to `config/quality_baseline.py`:

```python
MY_NEW_DIMENSION = QualityDimension(
    name="my_dimension",
    description="What this checks",
    severity_if_failed=Severity.MAJOR,
    pass_threshold=7,
    scoring=[
        ScoringLevel(10, "Perfect", "No issues"),
        ScoringLevel(7, "Good", "Minor issues"),
        ScoringLevel(4, "Problems", "Needs work"),
        ScoringLevel(1, "Broken", "Fundamentally wrong"),
    ],
)
```

Then add it to the relevant baseline:
```python
BASELINE_MC_BLOCK = QualityBaseline(
    dimensions=_UNIVERSAL + _CODE_COMMON + [CHOICE_LINE_ACCURACY, MY_NEW_DIMENSION],
)
```

### Add a new fix strategy

1. Create `ironclaw/skills/fix-myissue/SKILL.md` with frontmatter
2. Add the strategy to `STRATEGIES` dict in `sjqqc/pipeline.py`:

```python
"fix_myissue": {
    "allowed_fields": ["stem"],  # what it can change
    "system": "You are QuestionQualityClaw executing fix_myissue...",
},
```

3. Add execution logic in `execute_strategy()`:

```python
elif strategy_name == "fix_myissue":
    new_value = parsed.get("new_value", "")
    if new_value:
        current, fc = update_stem(current, new_value, strategy=strategy_name)
        fc.validated = True
        changes.append(fc)
```

### Add a new question type

1. Add to `PromptType` enum in `sjqqc/models.py`
2. Add `describe_choice()` handling in `AssessmentQuestion`
3. Add `_validate_choice_structure()` in `sjqqc/tools.py`
4. Add validation in `check_structural_quality()` in `sjqqc/quality.py`
5. Create a new baseline in `config/quality_baseline.py`
6. Add typeId hint in `pipeline.py` `execute_strategy()`

### Connect to your platform API

Replace file-based loading with API calls:

```python
# In sjqqc/loader.py or a new module
import httpx

async def fetch_questions_from_api(api_url, api_key):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_url}/questions",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return [AssessmentQuestion(**q) for q in resp.json()]

async def submit_revision(api_url, api_key, revision):
    platform_json = revision.revised.to_platform_json()
    async with httpx.AsyncClient() as client:
        await client.put(
            f"{api_url}/questions/{revision.question_path}",
            headers={"Authorization": f"Bearer {api_key}"},
            json=platform_json,
        )
```

## Workflow Summary

```
Your platform → export questions as JSON → questions/
Your reviewers → write feedback → questions/*.feedback.json
                                  or Telegram /feedback
                                  or CLI process command

QuestionQualityClaw → validate → improve → export

Revised JSON → upload back to platform
            → GitHub PR for review
            → Linear ticket for tracking
```
