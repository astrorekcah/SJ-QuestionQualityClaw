# WARP.md

## Project Overview
SJ-QuestionQualityClaw is a feedback-driven assessment question quality agent. It reads questions from GitHub, validates reviewer feedback via OpenRouter, applies targeted fixes through an IronClaw skill pipeline, and tracks everything in Linear. Output is always exact platform JSON format, directly uploadable.

## Essential Commands
```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env

# Run
python scripts/run.py process question.json "feedback text"
python scripts/run.py quality question.json
python scripts/run.py export question.json

# Test + Lint
pytest tests/ -v
ruff check sjqqc/ tests/ config/
```

## Architecture
- `sjqqc/pipeline.py` — ImprovementPipeline: classify() → execute_strategy() → assemble(). Each strategy gets a focused LLM call, tools apply changes atomically.
- `sjqqc/reviewer.py` — QuestionReviewer: validate_feedback(), improve_question() (delegates to pipeline), quality_check(), process_feedback() (end-to-end).
- `sjqqc/tools.py` — Atomic mutation tools: update_answer/code/stem/choice, reindex_choices, validate_step, validate_roundtrip, export_platform_json.
- `sjqqc/changelog.py` — Field-level diff: diff_fields(), build_changelog().
- `sjqqc/models.py` — AssessmentQuestion (platform-exact), FeedbackComment, FeedbackValidation, QuestionRevision, FieldChange, ImprovementStep, ImprovementChangelog, QuestionAuditTrail.
- `sjqqc/github_client.py` — GitHubQuestionClient: get_question, list_questions, create_revision_pr, create_feedback_issue.
- `sjqqc/linear_client.py` — LinearClient: create_feedback_ticket, post_validation, post_revision, update_state, post_escalation.

## IronClaw Skills (`ironclaw/skills/`)
8 strategy skills + 2 orchestration skills. Each declares allowed fields and calls specific tools.

## Platform JSON Format
Three question types: mc-block (start/end), mc-code (code arrays), mc-line (line numbers). Round-trip validated via tools.validate_roundtrip().

## Documentation
- `docs/FEEDBACK_LOOP.md` — complete workflow: input → validate → classify → fix → export
- `README.md` — setup, architecture, module guide
- `ironclaw/workspace/IDENTITY.md` — agent identity + system architecture
- `ironclaw/skills/` — 10 skill playbooks

## Testing
70 tests in tests/unit/ using bundled fixtures (tests/fixtures/). Pipeline tests mock LLM responses. No external dependencies needed.
