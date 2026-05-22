from __future__ import annotations


def render_postgres_schema() -> str:
    return POSTGRES_SCHEMA.strip() + "\n"


APPEND_ONLY_TABLES = [
    "events",
    "attempt_lifecycle_events",
    "attempts",
    "tool_calls",
    "decisions",
    "approvals",
]


def _append_only_triggers() -> str:
    return "\n\n".join(
        f"""CREATE TRIGGER trg_protect_{table}
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();"""
        for table in APPEND_ONLY_TABLES
    )


POSTGRES_SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    artifact_type VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    version INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS policy_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    rule_definition JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attempt_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL,
    state VARCHAR(50) NOT NULL CHECK (state IN ('started', 'running', 'finished')),
    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    input JSONB NOT NULL,
    output JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES attempts(id),
    gate_id UUID REFERENCES policy_gates(id),
    decision_maker VARCHAR(100) NOT NULL,
    action_taken VARCHAR(50) NOT NULL CHECK (action_taken IN ('allowed', 'blocked', 'approval_requested')),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES attempts(id),
    tool_name VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES attempts(id),
    failure_type VARCHAR(100) NOT NULL,
    context JSONB NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('open', 'analyzing', 'proposed', 'resolved', 'ignored')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS improvement_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    failure_id UUID NOT NULL REFERENCES failures(id),
    target_artifact_id UUID NOT NULL REFERENCES artifacts(id),
    target_artifact_name VARCHAR(255) NOT NULL,
    target_artifact_type VARCHAR(100) NOT NULL,
    target_artifact_version INT NOT NULL,
    base_artifact_hash VARCHAR(64) NOT NULL,
    patch_type VARCHAR(100) NOT NULL,
    proposed_content TEXT NOT NULL,
    validation_assertions JSONB NOT NULL,
    rollback_plan JSONB NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('draft', 'sandbox_verified', 'approved', 'rejected', 'applied')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS replays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES improvement_candidates(id),
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    validation_results JSONB NOT NULL,
    sandbox_schema VARCHAR(100),
    sandbox_env JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES improvement_candidates(id),
    approved_by VARCHAR(100) NOT NULL,
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected')),
    comments TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION prevent_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'IMPERMISSIBLE ACTION: Table % is append-only. UPDATE or DELETE operations are prohibited.', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

{_append_only_triggers()}

CREATE OR REPLACE VIEW view_orphan_attempts AS
SELECT
    le.attempt_id,
    MAX(le.created_at) AS last_active_at,
    ARRAY_AGG(le.state ORDER BY le.created_at) AS lifecycle_history
FROM attempt_lifecycle_events le
LEFT JOIN attempts a ON le.attempt_id = a.id
WHERE a.id IS NULL
GROUP BY le.attempt_id
HAVING MAX(le.created_at) < NOW() - INTERVAL '5 minutes';
"""
