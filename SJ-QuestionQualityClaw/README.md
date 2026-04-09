# SJ-QuestionQualityClaw

Feedback-driven assessment question quality agent. Reads questions from GitHub, validates reviewer feedback via OpenRouter, applies targeted fixes through an IronClaw skill pipeline, and tracks everything in Linear.

## Quick Start

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # Fill in API keys
pytest tests/ -v       # 80 tests
```

## Usage

```bash
# Process feedback on a question
python scripts/run.py process question.json "The correct answer should be D, not C"

# Quality check
python scripts/run.py quality question.json

# Export platform JSON
python scripts/run.py export question.json
```

## Architecture

```
GitHub (question bank)
  ↓ read question JSON
IronClaw Agent (pipeline)
  ↓ validate_feedback() via OpenRouter
  ↓ classify → pick strategy skills
  ↓ execute: fix_code → fix_answer → fix_choices → ...
  ↓ each skill calls sjqqc.tools (apply + validate)
  ↓ assemble changelog + export platform JSON
GitHub (PR with revised question)
  ↓ linked to
Linear (ticket tracks entire cycle)
```

## Core Modules

- `sjqqc/pipeline.py` — IronClaw skill orchestrator: classify → execute → assemble
- `sjqqc/reviewer.py` — validate_feedback, improve_question (delegates to pipeline), quality_check
- `sjqqc/tools.py` — atomic mutation tools: update_answer, update_code, update_stem, update_choice, validate_step, export
- `sjqqc/changelog.py` — field-level diff engine
- `sjqqc/models.py` — AssessmentQuestion (platform-exact), FeedbackComment, FeedbackValidation, QuestionRevision, ImprovementChangelog
- `sjqqc/github_client.py` — read questions, create revision PRs, create issues
- `sjqqc/linear_client.py` — tickets, validation comments, revision comments, state management

## IronClaw Skills

- `classify_feedback` — analyze feedback → pick strategy list
- `fix_code` / `fix_answer` / `fix_stem` / `fix_choices` / `fix_scenario` / `fix_distractors`
- `assemble_and_export` / `manage_lifecycle` / `validate_and_improve`

## Configuration

`.env`:
- `OPENROUTER_API_KEY` + `SELECTED_MODEL` — LLM backend
- `GITHUB_TOKEN` + `GITHUB_REPO_OWNER` + `GITHUB_REPO_NAME` — question repo
- `LINEAR_API_KEY` + `LINEAR_TEAM_ID` — ticket management
