# Skill: Classify Feedback

## When to Use
First step in every feedback processing pipeline. Determines which
strategy skills to invoke based on the feedback content.

## Input
- `question`: AssessmentQuestion (loaded from platform JSON)
- `feedback`: FeedbackComment (the human's comment)

## Process
Analyze the feedback and classify it into one or more categories:

| Feedback Pattern | Category | Strategy Skill |
|---|---|---|
| "wrong answer", "answer should be X" | answer_correction | fix_answer |
| "code bug", "syntax error", "logic flaw" | code_fix | fix_code |
| "unclear", "confusing", "ambiguous stem" | stem_clarity | fix_stem |
| "choice X is also correct", "choice Y is wrong" | choice_issue | fix_choices |
| "unrealistic scenario", "contrived example" | scenario_issue | fix_scenario |
| "too obvious", "trivially eliminated" | distractor_issue | fix_distractors |

## Output
Ordered list of strategy skills to run. Order matters:
1. `fix_code` first (code changes may affect choice references)
2. `fix_answer` second (answer changes are highest priority)
3. `fix_choices` third (choice content may depend on code)
4. `fix_stem` / `fix_scenario` / `fix_distractors` last

## Example
Feedback: "Line 80 has a bug and because of that the correct answer should be D not C"
→ Strategies: [`fix_code`, `fix_answer`]
