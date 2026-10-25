"""The schema of a database made before Alembic: what init_db's create_all
plus ADD COLUMN left behind, exactly as data/chamapro.db had it on
2026-10-26. Migration tests start from this, never from the current models."""
import sqlite3

LEGACY_SCHEMA = """
CREATE TABLE applicants (
    id INTEGER NOT NULL, name VARCHAR(200), created_at DATETIME NOT NULL,
    age INTEGER, sex VARCHAR(10), education INTEGER, marital_status VARCHAR(10),
    PRIMARY KEY (id));
CREATE TABLE interviews (
    id INTEGER NOT NULL, applicant_id INTEGER NOT NULL, status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL, question_set VARCHAR(8) NOT NULL DEFAULT 'v1',
    language VARCHAR(8) NOT NULL DEFAULT 'kik', mode VARCHAR(10) NOT NULL DEFAULT 'live',
    PRIMARY KEY (id), FOREIGN KEY(applicant_id) REFERENCES applicants (id));
CREATE TABLE responses (
    id INTEGER NOT NULL, interview_id INTEGER NOT NULL, sentence_no INTEGER NOT NULL,
    domain VARCHAR(40), audio_path TEXT NOT NULL, duration_s FLOAT, status VARCHAR(20) NOT NULL,
    error TEXT, transcript TEXT, transcript_asr TEXT, asr_model VARCHAR(200), asr_seconds FLOAT,
    transcribed_at DATETIME, edited BOOLEAN NOT NULL, edited_at DATETIME, translation TEXT,
    signals JSON, translated_at DATETIME, created_at DATETIME NOT NULL,
    source VARCHAR(10) NOT NULL DEFAULT 'audio',
    PRIMARY KEY (id), UNIQUE (interview_id, sentence_no),
    FOREIGN KEY(interview_id) REFERENCES interviews (id));
CREATE INDEX ix_responses_interview_id ON responses (interview_id);
CREATE TABLE assessments (
    id INTEGER NOT NULL, interview_id INTEGER NOT NULL, risk_class VARCHAR(20) NOT NULL,
    probabilities JSON NOT NULL, feature_vector JSON NOT NULL, contributions JSON NOT NULL,
    extracted JSON NOT NULL, extraction_completeness FLOAT NOT NULL,
    features_populated INTEGER NOT NULL, features_total INTEGER NOT NULL,
    features_not_extractable JSON NOT NULL, extraction_model VARCHAR(200) NOT NULL,
    model_file VARCHAR(200) NOT NULL, model_sha256 VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL, assessed_by VARCHAR(64), applicant_form JSON,
    PRIMARY KEY (id), UNIQUE (interview_id), FOREIGN KEY(interview_id) REFERENCES interviews (id));
CREATE TABLE decisions (
    id INTEGER NOT NULL, interview_id INTEGER NOT NULL, decision VARCHAR(20) NOT NULL,
    note TEXT, created_at DATETIME NOT NULL, decided_by VARCHAR(64),
    PRIMARY KEY (id), UNIQUE (interview_id), FOREIGN KEY(interview_id) REFERENCES interviews (id));
CREATE TRIGGER assessments_no_update BEFORE UPDATE ON assessments
    BEGIN SELECT RAISE(ABORT, 'assessments are immutable'); END;
CREATE TRIGGER assessments_no_delete BEFORE DELETE ON assessments
    BEGIN SELECT RAISE(ABORT, 'assessments are immutable'); END;
CREATE TRIGGER decisions_no_update BEFORE UPDATE ON decisions
    BEGIN SELECT RAISE(ABORT, 'decisions are immutable'); END;
CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
    BEGIN SELECT RAISE(ABORT, 'decisions are immutable'); END;
CREATE TABLE users (
    id INTEGER NOT NULL, username VARCHAR(64) NOT NULL, password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL,
    email VARCHAR(254), PRIMARY KEY (id), UNIQUE (username));
CREATE TABLE sessions (
    token_hash VARCHAR(64) NOT NULL, user_id INTEGER NOT NULL, created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL, auth_method VARCHAR(20), PRIMARY KEY (token_hash),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE);
CREATE INDEX ix_sessions_user_id ON sessions (user_id);
CREATE UNIQUE INDEX ix_users_email ON users (email);
"""


def make_legacy_db(path, extra_sql: str = "") -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(LEGACY_SCHEMA + extra_sql)
        con.commit()
    finally:
        con.close()
