-- SJ-QuestionQualityClaw: Initial Schema
-- Questions, reviews, feedback, and revision history

CREATE TABLE IF NOT EXISTS questions (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    question_type   TEXT NOT NULL DEFAULT 'multiple_choice',
    difficulty      TEXT NOT NULL DEFAULT 'intermediate',
    domain          TEXT NOT NULL DEFAULT 'general',
    tags            JSONB NOT NULL DEFAULT '[]',
    choices         JSONB NOT NULL DEFAULT '[]',
    correct_answer  TEXT,
    reference_material TEXT,
    state           TEXT NOT NULL DEFAULT 'draft',
    author          TEXT,
    github_pr_url   TEXT,
    linear_ticket_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reviews (
    id              TEXT PRIMARY KEY,
    question_id     TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL,
    overall_score   REAL NOT NULL,
    criterion_scores JSONB NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    suggestions     JSONB NOT NULL DEFAULT '[]',
    revised_body    TEXT,
    revised_choices JSONB,
    reviewer_model  TEXT NOT NULL DEFAULT 'unknown',
    raw_llm_response JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS revision_history (
    id              SERIAL PRIMARY KEY,
    question_id     TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    version         INT NOT NULL,
    question_snapshot JSONB NOT NULL,
    review_id       TEXT REFERENCES reviews(id),
    comparison      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(question_id, version)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_questions_state ON questions(state);
CREATE INDEX IF NOT EXISTS idx_questions_domain ON questions(domain);
CREATE INDEX IF NOT EXISTS idx_reviews_question_id ON reviews(question_id);
CREATE INDEX IF NOT EXISTS idx_revision_history_question ON revision_history(question_id);
