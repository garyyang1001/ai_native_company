from __future__ import annotations


def render_postgres_schema() -> str:
    return POSTGRES_SCHEMA.strip() + "\n"


# `events` is NOT append-only — it's a sensor log that may be pruned by
# retention cron (Gary 2026-05-28 Phase 4 decision; see
# docs/plans/2026-05-28-learning-loop-design-v0.2.md Q5).
# attempts / attempt_envelopes / failures / approvals / artifacts remain
# append-only because they carry contract-level facts.
APPEND_ONLY_TABLES = [
    "attempt_lifecycle_events",
    "attempts",
    "attempt_envelopes",
    "tool_calls",
    "decisions",
    "approvals",
]


def _append_only_triggers() -> str:
    sql = "\n\n".join(
        f"""DROP TRIGGER IF EXISTS trg_protect_{table} ON {table};
CREATE TRIGGER trg_protect_{table}
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();"""
        for table in APPEND_ONLY_TABLES
    )
    # Explicitly drop any historical trigger on `events` left over from
    # earlier deployments that listed it as append-only.
    sql += "\n\nDROP TRIGGER IF EXISTS trg_protect_events ON events;"
    return sql


POSTGRES_SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    parent_team_id UUID REFERENCES teams(id),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    team_id UUID NOT NULL REFERENCES teams(id),
    profile JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_owner_team_id UUID NOT NULL REFERENCES teams(id),
    required_approver_team_id UUID NOT NULL REFERENCES teams(id),
    rule_definition JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (artifact_owner_team_id, required_approver_team_id)
);

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

CREATE TABLE IF NOT EXISTS pattern_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_signature VARCHAR(255) NOT NULL,
    artifact_id UUID NOT NULL REFERENCES artifacts(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pattern_routes_active_unique
    ON pattern_routes (pattern_signature) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_pattern_routes_signature
    ON pattern_routes (pattern_signature) WHERE is_active = TRUE;

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

-- Agent Output Envelope per docs/company-data-contract-v0.md §6.
-- Sidecar to `attempts` so we can carry contract-required fields without
-- breaking the 15+ existing consumers of `attempts`. See
-- docs/plans/2026-05-28-learning-loop-design-v0.2.md (Phase 2, Q1=B).
CREATE TABLE IF NOT EXISTS attempt_envelopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE RESTRICT,

    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,

    output_type TEXT NOT NULL,
    human_artifact_path TEXT,
    machine_record JSONB NOT NULL,
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,

    confidence TEXT NOT NULL CHECK (
        confidence IN ('low', 'medium', 'high', 'unknown')
    ),
    recommended_next_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_required BOOLEAN NOT NULL DEFAULT FALSE,
    review_required BOOLEAN NOT NULL DEFAULT FALSE,
    retention_policy TEXT NOT NULL,

    content_hash TEXT NOT NULL,
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

-- 治理層 FK：既有 11 表加上 team / agent 歸屬欄位（idempotent ALTER）
-- artifacts 屬於哪個團隊 / failures 由哪個 agent 偵測 / improvement_candidates 由哪個 agent 提出
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS owner_team_id UUID REFERENCES teams(id);
ALTER TABLE failures ADD COLUMN IF NOT EXISTS detected_by_agent_id UUID REFERENCES agents(id);
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS proposed_by_agent_id UUID REFERENCES agents(id);

-- V0.3 Phase 2 simple版 (Gary 2026-05-29 拍板;Round 4 codex conditional GO)
-- gemma4 daily_curate 把 actionable 寫成可批准的候選 row。
-- simple 版不走 artifact-patch 路線,所以既有 NOT NULL 欄位(假設 V0.2 OHYA-style
-- failure-driven patch)放寬為 NULL-able;新加 4 個 op-assistant 專用欄位。
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS proposal_type TEXT;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS typed_payload JSONB;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS source_event_id UUID;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS approved_by TEXT;

ALTER TABLE improvement_candidates ALTER COLUMN failure_id DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN target_artifact_id DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN target_artifact_name DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN target_artifact_type DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN target_artifact_version DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN base_artifact_hash DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN patch_type DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN proposed_content DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN validation_assertions DROP NOT NULL;
ALTER TABLE improvement_candidates ALTER COLUMN rollback_plan DROP NOT NULL;

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
