# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

SJ-QuestionQualityClaw is an assessment question quality review agent built on IronClaw. It manages the full lifecycle of assessment questions — ingestion, multi-pass LLM-driven quality review, automated revision, and publication — orchestrating GitHub (question storage), Linear (ticket tracking), and LLM review analysis.

## Essential Commands

```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env

# Run
python scripts/run.py review question.json     # Single review
python scripts/run.py multi question.json      # Multi-pass
python scripts/run.py batch <domain>           # Batch review
python scripts/run.py revise question.json     # Auto-revise

# Test
pytest tests/unit/ -v
pytest tests/ -v

# Lint
ruff check sjqqc/ tests/ config/
```

## Architecture

### Core Engine (`sjqqc/reviewer.py`)
`QuestionReviewer` with 5 modes: `review()`, `multi_pass()`, `compare()`, `batch()`, `revise()`. All modes return structured Pydantic models. LLM communication via `_LLMClient` (OpenRouter-compatible).

### Models (`sjqqc/models.py`)
- `Question` — assessment question with choices, metadata, lifecycle state
- `Review` — per-criterion scores, verdict, suggestions, raw LLM response
- `Feedback` — consensus across multi-pass reviews, disputed criteria detection
- `ComparisonResult` — per-criterion deltas between question versions
- `BatchReport` — aggregate stats across a batch of reviews
- `RevisionHistory` — full audit trail with score trajectory

### Integrations
- `sjqqc/github_client.py` — `GitHubQuestionClient`: questions as JSON in GitHub repo, PRs for changes, issues for quality flags
- `sjqqc/linear_client.py` — `LinearClient`: ticket CRUD via GraphQL, state sync, review comments
- `config/review_criteria.py` — 7-criterion weighted rubric with scoring guides
- `config/settings.py` — all tunables: review params, API config, database

### IronClaw Agent (`ironclaw/`)
- `workspace/IDENTITY.md` — agent persona, capabilities, operating principles
- `skills/review_question.md` — maps reviewer engine modes to operational workflows
- `skills/manage_lifecycle.md` — full lifecycle orchestration with code examples

## Key Patterns

- **Async-first**: all I/O uses async/await (httpx, asyncpg)
- **Pydantic models**: all data flows through validated models
- **Structured LLM output**: JSON schemas enforced via system prompts
- **Weighted scoring**: rubric criteria have different weights, correctness highest (3.0x)
- **Temperature variation**: multi-pass reviews use spread (0.15–0.45) for diverse evaluation
- **Concurrency control**: batch reviews use asyncio.Semaphore

## Testing

- Unit tests: `tests/unit/` — models, rubric, scoring logic (no external deps)
- Integration tests: `tests/integration/` — GitHub, Linear API stubs
- `pytest-asyncio` for async test support
- `ruff` for linting (line-length 100, Python 3.11+)

## Database

PostgreSQL via docker-compose. Schema in `migrations/001_initial_schema.sql`:
- `questions` table with JSONB columns for choices/tags
- `reviews` table with full LLM response storage
- `revision_history` for audit trail
