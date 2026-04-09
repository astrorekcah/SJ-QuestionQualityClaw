# Skill: Assemble & Export

## When to Use
Final step after all strategy skills have run. Merges results,
validates the final question, builds the changelog, and exports
platform-ready JSON.

## Process
1. Collect the final question state (after all strategy skills applied changes)
2. Run final validation:
   ```python
   tools.validate_roundtrip(original, revised)
   ```
3. Build the changelog:
   ```python
   from sjqqc.changelog import build_changelog
   changelog = build_changelog(original, revised, steps=pipeline_steps, feedback_id=feedback.id)
   ```
4. Export platform JSON:
   ```python
   json_str = tools.export_platform_json(revised)
   ```

## Output
- `revised_question`: AssessmentQuestion (exact platform format)
- `changelog`: ImprovementChangelog with field-level diffs
- `platform_json`: str (ready to upload)

## Validation Checks
- Round-trip: export → re-parse succeeds
- Structural: same typeId, same choice keys, valid answer reference
- Changelog: all steps have validation.passed == True
- If any step failed validation, STOP and report errors

## Changelog Summary
The changelog.summary dict shows at a glance what changed:
```python
{
    "answer_changed": True/False,
    "code_changed": True/False,
    "choices_changed": True/False,
    "stem_changed": True/False,
}
```

## Linear Integration
After export, create a Linear ticket comment with:
- Feedback text
- Validation verdict
- Changelog summary
- Link to the exported JSON / GitHub PR
