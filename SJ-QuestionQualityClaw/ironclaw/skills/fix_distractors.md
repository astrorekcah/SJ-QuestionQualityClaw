# Skill: Fix Distractors

## When to Use
Feedback says wrong choices are too obvious, trivially eliminated,
or implausible.

## Allowed Fields
- `prompt.configuration.choices` (non-correct choices only)

## Process
1. Identify which distractors are weak
2. Generate more plausible alternatives that test real misconceptions
3. For each weak distractor:
   `tools.update_choice(question, key, new_content, strategy="fix_distractors")`
4. `tools.validate_step(original, updated)` — must pass

## Validation
- Answer key unchanged
- Updated distractors are different from the correct answer
- Distractors are technically wrong but plausibly confusing

## Constraints
- NEVER modify the correct answer's choice
- Keep the same choice structure per typeId
- Distractors should test real misconceptions, not be random
