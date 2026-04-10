# SJ-QuestionQualityClaw

Feedback-driven assessment question quality agent. Validates reviewer feedback, applies targeted improvements through an IronClaw skill pipeline, and outputs platform-exact JSON ready for re-upload.

## Setup (3 commands)

```bash
git clone https://github.com/astrorekcah/SJ-QuestionQualityClaw.git
cd SJ-QuestionQualityClaw
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
# Required: OPENROUTER_API_KEY (get from https://openrouter.ai)
# Optional: GITHUB_TOKEN, LINEAR_API_KEY, LINEAR_TEAM_ID
```

## Test

```bash
pytest tests/ -v         # 80+ tests, no API keys needed
ruff check sjqqc/ tests/ # Lint
```

## Run

```bash
# Bank-wide quality assessment (instant, no LLM)
python scripts/run.py assess

# Process feedback on a question (requires OpenRouter key)
python scripts/run.py process questions/example.json "The answer should be D"

# LLM quality check
python scripts/run.py quality questions/example.json

# Export platform JSON
python scripts/run.py export questions/example.json

# Interactive demo (7 steps, live pipeline)
python scripts/demo.py
```

## Architecture

```
GitHub (question bank) ─── read question JSON
        │
QuestionQualityClaw (IronClaw agent)
        │
        ├── validate_feedback()     ← is the comment correct?
        │       via OpenRouter LLM
        │
        ├── ImprovementPipeline     ← if valid, improve the question
        │   ├── classify()          ← pick strategy skills
        │   ├── execute_strategy()  ← each skill calls tools atomically
        │   │   fix_code → fix_answer → fix_choices → ...
        │   └── assemble()          ← changelog + validate + export
        │
        └── export_platform_json()  ← exact format, uploadable as-is
        │
GitHub (PR with revised JSON) ──── linked to ──── Linear (ticket)
```

## Modules

| Module | Purpose |
|--------|---------|
| `sjqqc/llm.py` | Shared LLM client (OpenRouter, JSON extraction, error handling) |
| `sjqqc/reviewer.py` | validate_feedback, improve_question, quality_check, process_feedback |
| `sjqqc/pipeline.py` | ImprovementPipeline: classify → execute strategies → assemble |
| `sjqqc/tools.py` | Atomic mutation tools: update_answer/code/stem/choice, validate, export |
| `sjqqc/changelog.py` | Field-level diff engine: diff_fields, build_changelog |
| `sjqqc/quality.py` | Batch assessment: check_structural_quality, assess_bank, BankReport |
| `sjqqc/models.py` | All data models: AssessmentQuestion, FeedbackComment, QuestionRevision, etc. |
| `sjqqc/github_client.py` | Read questions, create PRs, create issues |
| `sjqqc/linear_client.py` | Ticket lifecycle, validation comments, changelog posts |
| `config/quality_baseline.py` | 12 quality dimensions, 4 type-specific baselines |
| `config/settings.py` | All configuration (DB, API, review params) |

## IronClaw Skills

```
ironclaw/skills/
├── classify_feedback.md      ← pick strategies from feedback
├── fix_answer.md             ← correct the marked answer
├── fix_code.md               ← fix code bugs/syntax
├── fix_stem.md               ← improve question clarity
├── fix_choices.md            ← revise choice content
├── fix_scenario.md           ← rewrite unrealistic scenarios
├── fix_distractors.md        ← improve wrong choice plausibility
├── assemble_and_export.md    ← validate + changelog + export
├── manage_lifecycle.md       ← GitHub + Linear orchestration
└── validate_and_improve.md   ← end-to-end workflow
```

## Question Types

| Type | Choices | Example |
|------|---------|---------|
| `mc-block` | `{key, start, end}` — code line ranges | Ruby auth, Rust integrity |
| `mc-code` | `{key, code: [...]}` — inline snippets | Go deserialization, Ruby auth |
| `mc-line` | `{key, choice: N}` — single line numbers | Go path traversal, Python race condition |
| `mc-generic` | `{key, choice: "text"}` — text choices | AI/LLM RAG, model watermarking |

## Quality Baseline

12 dimensions scored per question, severity-ranked:

**Critical**: answer_correctness, single_correct_answer, domain_accuracy, vulnerability_presence, choice_line_accuracy
**Major**: stem_clarity, distractor_plausibility, code_syntactic_validity, code_choice_quality, generic_choice_quality
**Minor**: scenario_realism, code_realism

## Prerequisites

- Python 3.11+
- `uv` package manager
- Docker (optional, for PostgreSQL)
- OpenRouter API key (for LLM features)
