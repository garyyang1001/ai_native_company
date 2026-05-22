-- Ohya SEO Growth OS core schema v1
-- Draft only. Do not run against production without Gary approval.

CREATE SCHEMA IF NOT EXISTS seo_os;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS seo_os.tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  source text NOT NULL CHECK (source IN ('telegram', 'priority_scan', 'cannibalization', 'fact_check', 'manual', 'gsc', 'neo4j', 'payload', 'cron', 'system')),
  type text NOT NULL CHECK (type IN ('new_article', 'research', 'outline', 'write', 'link_fix', 'audit', 'refresh', 'merge', 'redirect', 'fact_check', 'query', 'publish', 'performance_review', 'internal_link_fix', 'priority_scan', 'cannibalization_scan', 'weekly_report')),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'awaiting_approval', 'done', 'failed', 'cancelled', 'archived')),
  priority text NOT NULL DEFAULT 'medium' CHECK (priority IN ('urgent', 'high', 'medium', 'low')),
  slug text,
  url text,
  payload_post_id text,
  assigned_agent text CHECK (assigned_agent IS NULL OR assigned_agent IN ('coordinator', 'article-editor', 'topic-researcher', 'outline-planner', 'writer', 'link-finder', 'seo-graph', 'system')),
  parent_task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  input_summary text,
  next_action text,
  owner_type text CHECK (owner_type IS NULL OR owner_type IN ('gary', 'consultant', 'supervisor', 'agent', 'system')),
  owner_id text,
  failure_reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON seo_os.tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_slug ON seo_os.tasks(slug);
CREATE INDEX IF NOT EXISTS idx_tasks_type_created ON seo_os.tasks(type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_agent ON seo_os.tasks(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON seo_os.tasks(parent_task_id);

CREATE TABLE IF NOT EXISTS seo_os.agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  agent text NOT NULL CHECK (agent IN ('coordinator', 'article-editor', 'topic-researcher', 'outline-planner', 'writer', 'link-finder', 'seo-graph', 'system')),
  profile text,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed', 'timeout', 'cancelled')),
  input_prompt text,
  final_message text,
  stdout_path text,
  stderr_path text,
  exit_code integer,
  duration_seconds integer,
  model_provider text,
  model_name text,
  token_usage jsonb,
  error_message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON seo_os.agent_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_started ON seo_os.agent_runs(agent, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON seo_os.agent_runs(status);

CREATE TABLE IF NOT EXISTS seo_os.artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  agent_run_id uuid REFERENCES seo_os.agent_runs(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  type text NOT NULL CHECK (type IN ('research_report', 'research_summary', 'outline', 'outline_json', 'draft', 'final_article', 'audit_report', 'patch_plan', 'fix_queue', 'link_audit', 'performance_report', 'gsc_raw', 'competitor_snapshot', 'google_doc', 'manifest', 'weekly_report', 'schema_json', 'migration_sql', 'other')),
  path text NOT NULL,
  google_doc_url text,
  slug text,
  url text,
  agent text,
  summary text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'archived', 'deleted')),
  sha256 text,
  mime_type text,
  size_bytes bigint,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_artifacts_task ON seo_os.artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_agent_run ON seo_os.artifacts(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_slug ON seo_os.artifacts(slug);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON seo_os.artifacts(type);
CREATE INDEX IF NOT EXISTS idx_artifacts_path ON seo_os.artifacts(path);

CREATE TABLE IF NOT EXISTS seo_os.workflow_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  agent_run_id uuid REFERENCES seo_os.agent_runs(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  event_type text NOT NULL CHECK (event_type IN ('task_created', 'task_started', 'task_updated', 'task_completed', 'task_failed', 'agent_dispatched', 'agent_completed', 'agent_failed', 'artifact_created', 'approval_requested', 'approval_approved', 'approval_rejected', 'decision_recorded', 'article_published', 'performance_checked', 'neo4j_signal_generated', 'report_generated')),
  actor_type text NOT NULL CHECK (actor_type IN ('gary', 'consultant', 'supervisor', 'agent', 'system')),
  actor_id text,
  message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_task ON seo_os.workflow_events(task_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_type_created ON seo_os.workflow_events(event_type, created_at DESC);
