---
name: fix-choices
version: "1.0.0"
description: Revise choice content for assessment questions
activation:
  keywords:
    - "fix choices"
    - "choice wrong"
    - "also correct"
    - "ambiguous choice"
  tags:
    - "assessment"
    - "fix"
    - "choices"
  max_context_tokens: 1200
---

# Skill: Fix Choices

## When to Use
Feedback about specific choices: ambiguous, also correct, technically wrong,
or poorly structured.

## Allowed Fields
- `prompt.configuration.choices` (content per typeId)

## Process
1. Identify which choice(s) need fixing
2. Build new content matching the typeId structure:
   - mc-block: `{"key": "x", "start": N, "end": N}`
   - mc-code: `{"key": "x", "code": ["line1", ...]}`
   - mc-line: `{"key": "x", "choice": N}`
3. Call `tools.update_choice(question, key, new_content, strategy="fix_choices")`
4. `tools.validate_step(original, updated)` — must pass

## Validation
- Same number of choices with same keys
- Correct structure per typeId
- If mc-block/mc-line: references point to valid code lines

## Constraints
- Keep the same choice keys (a, b, c, d)
- Do NOT change the number of choices
- Preserve the answer key unless fix_answer is also running
