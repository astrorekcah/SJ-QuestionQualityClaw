# Skill: Fix Code

## When to Use
Feedback identifies code issues: syntax errors, logic flaws, unrealistic patterns,
or vulnerabilities that don't match the question's intent.

## Allowed Fields
- `prompt.configuration.code` (line array)
- `prompt.configuration.choices` (line references — only via reindex_choices)

## Process
1. Identify the specific lines that need fixing
2. For single lines: `tools.update_code(question, line_idx, new_line, strategy="fix_code")`
3. For blocks: `tools.update_code_block(question, start, end, new_lines, strategy="fix_code")`
4. If line count changed: `tools.reindex_choices(question, line_delta, strategy="fix_code")`
5. `tools.validate_step(original, updated)` — must pass

## Validation
- Code is syntactically plausible for the stated language
- If mc-block or mc-line: choice line references are still valid
- Code line count preserved when possible (warning if changed)

## Constraints
- Preserve the security vulnerability the question is testing (don't accidentally fix it)
- Preserve line count when possible to avoid cascading choice reindex
- If line count changes, MUST call reindex_choices
