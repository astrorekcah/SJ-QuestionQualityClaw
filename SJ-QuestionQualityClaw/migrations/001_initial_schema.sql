-- SJ-QuestionQualityClaw: Schema matching platform AssessmentQuestion format
-- Stores questions, feedback, validations, revisions, and audit trail

CREATE TABLE IF NOT EXISTS questions (
    path              TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    parameters        JSONB NOT NULL DEFAULT '{}',
    prompt            JSONB NOT NULL,
    answers           JSONB NOT NULL DEFAULT '[]',
    state             TEXT NOT NULL DEFAULT 'active',
    linear_ticket_id  TEXT,
    github_pr_url     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback (
    id                TEXT PRIMARY KEY,
    question_path     TEXT NOT NULL REFERENCES questions(path) ON DELETE CASCADE,
    author            TEXT NOT NULL DEFAULT 'reviewer',
    comment           TEXT NOT NULL,
    target_choice     TEXT,
    target_lines      JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS validations (
    id                TEXT PRIMARY KEY,
    feedback_id       TEXT NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    question_path     TEXT NOT NULL REFERENCES questions(path) ON DELETE CASCADE,
    verdict           TEXT NOT NULL,
    confidence        REAL NOT NULL,
    reasoning         TEXT NOT NULL DEFAULT '',
    affected_areas    JSONB NOT NULL DEFAULT '[]',
    requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    suggested_action  TEXT NOT NULL DEFAULT 'no_action',
    raw_llm_response  JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS revisions (
    id                TEXT PRIMARY KEY,
    question_path     TEXT NOT NULL REFERENCES questions(path) ON DELETE CASCADE,
    feedback_id       TEXT NOT NULL REFERENCES feedback(id),
    validation_id     TEXT NOT NULL REFERENCES validations(id),
    original          JSONB NOT NULL,
    revised           JSONB NOT NULL,
    changes_made      JSONB NOT NULL DEFAULT '[]',
    rationale         TEXT NOT NULL DEFAULT '',
    changelog         JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id                SERIAL PRIMARY KEY,
    question_path     TEXT NOT NULL REFERENCES questions(path) ON DELETE CASCADE,
    event_type        TEXT NOT NULL,
    feedback_id       TEXT,
    validation_id     TEXT,
    revision_id       TEXT,
    summary           TEXT NOT NULL DEFAULT '',
    data              JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_questions_state ON questions(state);
CREATE INDEX IF NOT EXISTS idx_feedback_question ON feedback(question_path);
CREATE INDEX IF NOT EXISTS idx_validations_feedback ON validations(feedback_id);
CREATE INDEX IF NOT EXISTS idx_revisions_question ON revisions(question_path);
CREATE INDEX IF NOT EXISTS idx_audit_question ON audit_trail(question_path);
