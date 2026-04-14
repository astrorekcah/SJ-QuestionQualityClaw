# SJ-QuestionQualityClaw

Feedback-driven assessment question quality agent. Takes a platform JSON question file and a reviewer comment, validates whether the feedback is technically correct, applies targeted improvements through a multi-strategy pipeline, and outputs the revised question in the exact platform format — ready to upload back without modification.

## How It Works

```
Question (JSON) + Feedback (comment)
        │
        ├── validate_feedback()        Is the comment technically correct?
        │   └── LLM analyzes code, choices, answer against quality baseline
        │
        ├── ImprovementPipeline        If valid, improve the question
        │   ├── classify()             Pick strategy skills (fix_code, fix_answer, ...)
        │   ├── execute_strategy()     Each skill calls atomic tools + validates
        │   └── assemble()             Changelog + round-trip validation + export
        │
        └── Platform JSON out          Exact same format, directly uploadable
```

## Install

```bash
git clone https://github.com/astrorekcah/SJ-QuestionQualityClaw.git
cd SJ-QuestionQualityClaw
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
```

Edit `.env` with your keys:

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENROUTER_API_KEY` | Yes | LLM backend (get from https://openrouter.ai) |
| `SELECTED_MODEL` | No | Default: `anthropic/claude-sonnet-4` |
| `GITHUB_TOKEN` | For PRs | GitHub question repo access |
| `TELEGRAM_BOT_TOKEN` | For bot | Telegram feedback channel |
| `TELEGRAM_OWNER_ID` | For bot | Your Telegram user ID (security) |
| `LINEAR_API_KEY` | For tickets | Linear ticket tracking |
| `LINEAR_TEAM_ID` | For tickets | Linear team |

## Test

```bash
pytest tests/ -v        # 64 tests, no API keys needed
ruff check sjqqc/       # Lint
python scripts/test_e2e.py         # 5-phase offline end-to-end
python scripts/test_e2e.py --live  # 6-phase with OpenRouter
```

## Usage

### CLI Commands

```bash
# Bank-wide quality assessment (instant, no LLM)
python scripts/run.py assess

# Process feedback on a question (requires OpenRouter key)
python scripts/run.py process questions/file.json "The answer should be D, not C"

# LLM quality check (scores every dimension with rubric)
python scripts/run.py quality questions/file.json

# Export question as platform JSON
python scripts/run.py export questions/file.json

# Process all questions with the same feedback
python scripts/run.py batch-process "Check if the answer is correct"

# Start Telegram bot for receiving feedback via chat
python scripts/run.py telegram

# Interactive 7-step demo
python scripts/demo.py
```

### Feedback Files

Drop feedback files alongside questions using naming convention:

```
questions/ruby_auth.json              ← question
questions/ruby_auth.feedback.json     ← structured feedback
questions/ruby_auth.feedback.txt      ← or plain text
```

JSON feedback format:
```json
{
  "comment": "The answer should be D, not C",
  "author": "reviewer-name",
  "target_choice": "c",
  "target_lines": [66, 70]
}
```

### Telegram Bot

Message your bot with:
- `/feedback sc-aa-Ruby-863-2-v2 The answer should be D` — validate + improve
- `/assess` — bank quality report
- `/status` — system status + costs
- `/help` — commands

## Architecture

### Modules (14)

| Module | Lines | Purpose |
|--------|-------|---------|
| `sjqqc/models.py` | 364 | Platform question schema, feedback models, changelog models, audit trail |
| `sjqqc/llm.py` | 170 | OpenRouter API client with response caching, cost tracking, rate limiting, input sanitization |
| `sjqqc/reviewer.py` | 363 | validate_feedback, improve_question, quality_check, process_feedback with audit trail |
| `sjqqc/pipeline.py` | 400 | ImprovementPipeline: classify → execute 6 strategies → assemble changelog |
| `sjqqc/tools.py` | 358 | 8 atomic mutation tools + structural validation + round-trip validation + export |
| `sjqqc/changelog.py` | 123 | Field-level diff engine |
| `sjqqc/quality.py` | 413 | Structural quality checks, score cards, bank reports, priority queue |
| `sjqqc/cache.py` | 202 | SHA-256 response cache with TTL/LRU + per-model cost tracking |
| `sjqqc/loader.py` | 137 | Question + feedback file loader with pairing convention |
| `sjqqc/telegram_bridge.py` | 337 | Telegram bot: polls for messages, processes feedback, replies with results |
| `sjqqc/github_client.py` | 261 | Read questions, create revision PRs, create escalation issues |
| `sjqqc/linear_client.py` | 275 | Ticket lifecycle, validation comments, changelog posts |
| `sjqqc/db.py` | 140 | PostgreSQL persistence for audit trail (graceful fallback) |
| `config/quality_baseline.py` | 395 | 12 quality dimensions with 4-level numeric scoring rubrics |

### Pipeline Strategies

| Strategy | What it fixes | Allowed fields |
|----------|---------------|----------------|
| `fix_code` | Syntax errors, logic flaws, bugs | code lines, choice references |
| `fix_answer` | Wrong correct answer | answers array |
| `fix_stem` | Unclear question text | stem text |
| `fix_choices` | Choice content issues | choice content per typeId |
| `fix_scenario` | Unrealistic scenario | stem scenario portion |
| `fix_distractors` | Weak wrong choices | non-correct choices |

### Question Types

| Type | Choice format | Example |
|------|--------------|---------|
| `mc-block` | `{key, start, end}` — code line ranges | Ruby auth, Rust data integrity |
| `mc-code` | `{key, code: [...]}` — inline snippets | Go deserialization, Go SSRF |
| `mc-line` | `{key, choice: N}` — single line number | Python race condition, Rust privileges |
| `mc-generic` | `{key, choice: "text"}` — text answer | AI/LLM RAG, model watermarking |

## Quality Baseline

12 dimensions scored per question, each with a 4-level numeric rubric (10/7/4/1):

**Critical** (pass ≥ 8):
- `answer_correctness` — 10: definitively correct → 1: wrong
- `single_correct_answer` — 10: unambiguous → 1: multiple correct
- `domain_accuracy` — 10: technically impeccable → 1: fundamentally wrong
- `vulnerability_presence` — 10: clear vulnerability → 1: absent
- `choice_line_accuracy` — 10: exact references → 1: out of bounds

**Major** (pass ≥ 6-7):
- `stem_clarity` — 10: crystal clear → 1: incomprehensible
- `distractor_plausibility` — 10: excellent → 1: trivial
- `code_syntactic_validity` — 10: compiles clean → 1: wrong language
- `code_choice_quality` / `generic_choice_quality` — type-specific

**Minor** (pass ≥ 5):
- `scenario_realism` — 10: realistic → 1: impossible
- `code_realism` — 10: production-like → 1: toy code

## Security

- **Input sanitization**: all feedback text stripped of control characters and truncated to 50K before LLM prompts
- **API key validation**: warns on init, blocks calls if key is missing
- **Rate limiting**: 30 calls/minute sliding window prevents budget burn
- **Owner-only Telegram**: bot only responds to configured owner ID
- **Secrets management**: `.env` in `.gitignore`, no hardcoded secrets in source
- **Round-trip validation**: every revised question verified to be platform-uploadable

## IronClaw Skills

10 skills in `ironclaw/skills/*/SKILL.md` format with YAML frontmatter:

```
ironclaw/skills/
├── classify-feedback/     ← pick strategies from feedback
├── fix-answer/            ← correct the marked answer
├── fix-code/              ← fix code bugs/syntax
├── fix-stem/              ← improve question clarity
├── fix-choices/           ← revise choice content
├── fix-scenario/          ← rewrite unrealistic scenarios
├── fix-distractors/       ← improve wrong choice plausibility
├── assemble-and-export/   ← validate + changelog + export
├── manage-lifecycle/      ← GitHub + Linear orchestration
└── validate-and-improve/  ← end-to-end workflow
```

## Infrastructure

```bash
# Start PostgreSQL (optional, for audit persistence)
docker compose up -d

# Run database migrations
PGPASSWORD=sjqqc psql -h localhost -p 5433 -U sjqqc -d sjqqc_db -f migrations/001_initial_schema.sql
```

Tables: `questions`, `feedback`, `validations`, `revisions`, `audit_trail`

## Documentation

- `docs/FEEDBACK_LOOP.md` — complete 6-step workflow documentation
- `ironclaw/workspace/IDENTITY.md` — agent identity and system architecture
- `WARP.md` — AI development guide

## Prerequisites

- Python 3.11+
- `uv` package manager
- Docker (optional, for PostgreSQL)
- OpenRouter API key (for LLM features)
