---
name: fix-stem
version: "1.0.0"
description: Improve question stem clarity or fix technical inaccuracies
activation:
  keywords:
    - "fix stem"
    - "unclear"
    - "confusing"
    - "ambiguous"
  tags:
    - "assessment"
    - "fix"
    - "stem"
  max_context_tokens: 1200
---

# Skill: Fix Stem

## When to Use
Feedback says the question stem is unclear, misleading, or technically inaccurate.

## Allowed Fields
- `prompt.configuration.prompt` only

## Process
1. Identify what's unclear or inaccurate in the stem
2. Rewrite the stem addressing the feedback
3. Call `tools.update_stem(question, new_stem, strategy="fix_stem")`
4. `tools.validate_step(original, updated)` — must pass

## Validation
- Stem is non-empty
- Still asks the same fundamental question
- Language and terminology appropriate for the stated domain

## Constraints
- Do NOT change code, choices, or answer
- Preserve the difficulty level and domain focus
- Keep the scenario context if it's relevant to the security question
