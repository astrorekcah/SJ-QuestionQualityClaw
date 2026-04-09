# Skill: Review Question

## When to Use
Use this skill whenever a question needs quality evaluation. This is your
primary operational skill — it maps directly to the `QuestionReviewer` methods
in `sjqqc/reviewer.py`.

## Mode Selection

Choose the right mode based on the situation:

| Situation | Mode | Method |
|-----------|------|--------|
| Quick check on a single question | single | `reviewer.review(question)` |
| Question entering approval pipeline | multi_pass | `reviewer.multi_pass(question, passes=3)` |
| Checking if a revision fixed issues | comparative | `reviewer.compare(original, revised, original_review)` |
| Domain audit or pre-release gate | batch | `reviewer.batch(questions, concurrency=3)` |
| Auto-fixing a question that needs revision | revise | `reviewer.revise(question, review)` |

## Single Review Process
1. Parse question into `Question` model (validate type, choices, difficulty)
2. Call `reviewer.review(question)` → `Review`
3. Report: verdict, overall_score, per-criterion scores, suggestions
4. If verdict is FAIL or NEEDS_REVISION and auto-revise is enabled, chain to revise mode

## Multi-Pass Review Process
1. Call `reviewer.multi_pass(question, passes=N)` → `Feedback`
2. Engine runs N independent reviews at varying temperatures (0.15–0.45)
3. Aggregates into consensus: average score, majority verdict
4. Detects disputed criteria (score spread > 2 points across passes)
5. Report: consensus verdict, average score, disputed criteria, aggregated suggestions
6. If disputed criteria exist, recommend human review on those specific dimensions

## Comparative Review Process
1. Requires: original Question, revised Question, original Review
2. Call `reviewer.compare(original, revised, original_review)` → `ComparisonResult`
3. Engine reviews the revised question, then LLM-analyzes the diff
4. Report: score delta, per-criterion deltas, improvements, regressions, unresolved issues
5. Key decision: `revision_adequate` — if False, another revision cycle is needed

## Batch Review Process
1. Collect questions (from GitHub domain directory or explicit list)
2. Call `reviewer.batch(questions, concurrency=3)` → `BatchReport`
3. Engine reviews all questions with semaphore-controlled concurrency
4. Report: total/passed/failed counts, pass rate, average score
5. Highlight: common issues (appearing in 2+ questions), weakest criteria across batch
6. Use for periodic quality audits and pre-release checks

## Auto-Revision Process
1. Requires: Question + Review (the review that flagged issues)
2. Call `reviewer.revise(question, review)` → revised `Question`
3. Engine generates improved version preserving author intent
4. Always follow with a comparative review to validate the revision
5. Track in RevisionHistory for full audit trail

## Output Formatting

### For Telegram
```
📊 **Review: PASS** (7.8/10)
• correctness: 9/10 ✔️
• clarity: 7/10 — minor ambiguity in stem
• distractor_quality: 8/10 ✔️
💡 Suggestions: reword stem to clarify...
```

### For Slack (threaded)
Main message: verdict + score + 1-line summary
Thread replies: per-criterion details, suggestions, revision diff

### For CLI / JSON output
Return the full Review/Feedback/BatchReport model as JSON.

## Error Handling
- If an LLM call fails, log the error and retry once
- If a multi-pass review has partial failures, use available passes (minimum 1)
- If all passes fail, raise RuntimeError and notify operator
- Invalid question format → reject with validation error before calling LLM
