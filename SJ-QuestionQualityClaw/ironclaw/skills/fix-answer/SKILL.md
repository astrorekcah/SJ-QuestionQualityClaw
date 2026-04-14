---
name: fix-answer
version: "1.0.0"
description: Correct the marked answer key when feedback indicates it is wrong
activation:
  keywords:
    - "fix answer"
    - "wrong answer"
    - "correct answer"
    - "answer key"
  tags:
    - "assessment"
    - "fix"
    - "answer"
  max_context_tokens: 1200
---

# Skill: Fix Answer

## When to Use
Feedback indicates the marked correct answer is wrong.

## Allowed Fields
- `answers` array

## Process
1. Analyze the code and all choices to determine the actually correct answer
2. Call `tools.update_answer(question, new_key, reason=..., strategy="fix_answer")`
3. Call `tools.validate_step(original, updated)` — must pass
4. Return updated question + FieldChange

## Validation
- Exactly one answer in the answers array
- Answer key exists in choices
- The new answer is technically correct (verified by LLM analysis of the code)

## Constraints
- NEVER change choices or code in this skill — only the answer key
- If the answer change requires code changes, classify_feedback should also invoke fix_code
