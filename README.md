# SJ-QuestionQualityClaw

Assessment question quality review agent — IronClaw-powered, with GitHub, Linear, and LLM integration.

## Quick Start

```bash
# 1. Install
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. Configure
cp .env.example .env   # Fill in API keys

# 3. Test
pytest tests/unit/ -v

# 4. Review a question
python scripts/run.py review question.json
```

## Review Modes

```bash
# Single review (quick triage)
python scripts/run.py review question.json

# Multi-pass (3 independent reviews → consensus)
python scripts/run.py multi question.json

# Batch review a domain
python scripts/run.py batch security

# Auto-revise from feedback
python scripts/run.py revise question.json
```

## Architecture

```
QuestionReviewer (5 modes)
├── review()      — single-pass rubric evaluation
├── multi_pass()  — N reviews → consensus Feedback
├── compare()     — diff original vs. revised
├── batch()       — list of questions → BatchReport
└── revise()      — auto-generate improved question

GitHub Client                    Linear Client
├── questions as JSON in repo    ├── auto-create tickets
├── PRs for new/revised          ├── state sync (draft→approved)
└── issues for quality flags     └── review comments on tickets

IronClaw Agent
├── IDENTITY.md (agent persona + capabilities)
├── skills/ (review + lifecycle playbooks)
└── channels/ (Telegram, Slack, CLI)
```

## Quality Rubric

7 criteria, weighted (total 12.0):

- **Correctness** (3.0x) — Is the answer right?
- **Clarity** (2.0x) — Is the stem clear?
- **Distractor Quality** (2.0x) — Are wrong choices plausible?
- **Coverage** (1.5x) — Tests the intended domain?
- **Fairness** (1.5x) — Free from bias/tricks?
- **Difficulty Alignment** (1.0x) — Matches labeled difficulty?
- **Actionability** (1.0x) — Learner improves from getting it wrong?

Verdicts: PASS (≥7.0), NEEDS_REVISION (5.0–6.9), FAIL (<5.0)

## Tests

```bash
pytest tests/unit/ -v              # Unit tests (fast, no deps)
pytest tests/ -v                   # Full suite
ruff check sjqqc/ tests/ config/   # Lint
```

## Configuration

Environment variables (`.env`):

- `OPENROUTER_API_KEY` — LLM backend
- `SELECTED_MODEL` — Model to use (default: claude-sonnet-4-20250514)
- `GITHUB_TOKEN` — GitHub API access
- `LINEAR_API_KEY` + `LINEAR_TEAM_ID` — Linear ticket management
- `TELEGRAM_BOT_TOKEN` — Telegram channel (when configured)

All tunables in `config/settings.py`.
