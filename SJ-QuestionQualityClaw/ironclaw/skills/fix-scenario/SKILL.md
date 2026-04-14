---
name: fix-scenario
version: "1.0.0"
description: Rewrite unrealistic or contrived scenarios in question stems
activation:
  keywords:
    - "fix scenario"
    - "unrealistic"
    - "contrived"
  tags:
    - "assessment"
    - "fix"
    - "scenario"
  max_context_tokens: 1200
---

# Skill: Fix Scenario

## When to Use
Feedback says the scenario is unrealistic, contrived, or doesn't match
real-world security contexts.

## Allowed Fields
- `prompt.configuration.prompt` (scenario portion)

## Process
1. Identify what's unrealistic about the scenario
2. Rewrite the scenario portion while keeping the core question
3. Call `tools.update_stem(question, new_stem, strategy="fix_scenario")`
4. `tools.validate_step(original, updated)` — must pass

## Validation
- Stem still contains the actual question being asked
- Scenario is plausible for the stated programming language and domain
- Role/context is appropriate (e.g. security architect, developer)

## Constraints
- Only change the scenario framing, not the technical question
- Keep company names generic if replacing them
- Maintain the same difficulty level
