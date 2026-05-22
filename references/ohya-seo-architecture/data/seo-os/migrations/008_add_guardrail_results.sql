-- Ohya SEO Growth OS guardrail result persistence layer
-- Draft/local migration until Gary explicitly approves production migration.
-- Purpose: store deterministic seo-guardrail results, per-rule checks, rule registry snapshots,
-- and first-class guardrail workflow events for closed-loop dispatch gating.

BEGIN;

-- Make guardrail / scheduler task types first-class in the operational DB.
ALTER TABLE seo_os.tasks DROP CONSTRAINT IF EXISTS tasks_type_check;
ALTER TABLE seo_os.tasks ADD CONSTRAINT tasks_type_check CHECK (type IN (
  'new_article',
  'research',
  'outline',
  'write',
  'link_fix',
  'audit',
  'refresh',
  'merge',
  'redirect',
  'fact_check',
  'query',
  'publish',
  'performance_review',
  'internal_link_fix',
  'priority_scan',
  'cannibalization_scan',
  'weekly_report',
  'opportunity_scan',
  'pre_publish_audit',
  'cms_draft',
  'preview_verification',
  'cms_patch_plan',
  'media_asset',
  'video_produce',
  'video_replace',
  'guardrail_check',
  'feedback_snapshot',
  'next_task_generation',
  'learning_signal',
  'performance_feedback'
));

-- Make automated helpers visible as agent identities without using PostgreSQL enum.
ALTER TABLE seo_os.tasks DROP CONSTRAINT IF EXISTS tasks_assigned_agent_check;
ALTER TABLE seo_os.tasks ADD CONSTRAINT tasks_assigned_agent_check CHECK (
  assigned_agent IS NULL OR assigned_agent IN (
    'coordinator',
    'article-editor',
    'topic-researcher',
    'outline-planner',
    'writer',
    'link-finder',
    'seo-graph',
    'cms-draft-executor',
    'media-asset-generator',
    'video-producer',
    'seo-guardrail',
    'seo-performance-snapshot',
    'seo-performance-compare',
    'seo-next-task-rule',
    'seo-guardrail-scheduler',
    'system'
  )
);

ALTER TABLE seo_os.agent_runs DROP CONSTRAINT IF EXISTS agent_runs_agent_check;
ALTER TABLE seo_os.agent_runs ADD CONSTRAINT agent_runs_agent_check CHECK (
  agent IN (
    'coordinator',
    'article-editor',
    'topic-researcher',
    'outline-planner',
    'writer',
    'link-finder',
    'seo-graph',
    'cms-draft-executor',
    'media-asset-generator',
    'video-producer',
    'seo-guardrail',
    'seo-performance-snapshot',
    'seo-performance-compare',
    'seo-next-task-rule',
    'seo-guardrail-scheduler',
    'system'
  )
);

ALTER TABLE seo_os.artifacts DROP CONSTRAINT IF EXISTS artifacts_type_check;
ALTER TABLE seo_os.artifacts ADD CONSTRAINT artifacts_type_check CHECK (type IN (
  'research_report',
  'research_summary',
  'outline',
  'outline_json',
  'draft',
  'final_article',
  'audit_report',
  'patch_plan',
  'fix_queue',
  'link_audit',
  'performance_report',
  'gsc_raw',
  'competitor_snapshot',
  'google_doc',
  'manifest',
  'weekly_report',
  'schema_json',
  'migration_sql',
  'other',
  'opportunity_queue',
  'priority_queue',
  'priority_report',
  'cannibalization_report',
  'fact_check_report',
  'pre_publish_audit_report',
  'cms_draft_payload',
  'cms_preview_snapshot',
  'publish_checklist',
  'brand_asset',
  'media_asset_plan',
  'image_asset',
  'media_asset_report',
  'video_brief',
  'video_composition_html',
  'video_audio',
  'video_mp4',
  'video_thumbnail',
  'video_metadata',
  'video_caption',
  'video_upload_record',
  'guardrail_result',
  'guardrail_summary',
  'scheduler_run_report',
  'learning_signal_record'
));

ALTER TABLE seo_os.workflow_events DROP CONSTRAINT IF EXISTS workflow_events_event_type_check;
ALTER TABLE seo_os.workflow_events ADD CONSTRAINT workflow_events_event_type_check CHECK (
  event_type IN (
    'task_created',
    'task_started',
    'task_updated',
    'task_completed',
    'task_failed',
    'agent_dispatched',
    'agent_completed',
    'agent_failed',
    'artifact_created',
    'approval_requested',
    'approval_approved',
    'approval_rejected',
    'decision_recorded',
    'article_published',
    'performance_checked',
    'neo4j_signal_generated',
    'report_generated',
    'opportunity_detected',
    'next_task_created',
    'research_completed',
    'outline_completed',
    'draft_created',
    'links_verified',
    'pre_publish_audit_completed',
    'cms_draft_created',
    'preview_verified',
    'publish_ready',
    'feedback_task_created',
    'video_brief_created',
    'video_audio_synthesized',
    'video_rendered',
    'video_uploaded',
    'video_replaced',
    'video_feedback_received',
    'guardrail_checked',
    'guardrail_blocked',
    'guardrail_passed',
    'feedback_snapshot_scheduled',
    'learning_signal_recorded',
    'scheduler_run_started',
    'scheduler_run_completed',
    'scheduler_run_failed'
  )
);

CREATE TABLE IF NOT EXISTS seo_os.guardrail_rule_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  guardrail_id text NOT NULL,
  rule_version text NOT NULL DEFAULT 'mvp-v1',
  stage text NOT NULL CHECK (stage IN (
    'pre_dispatch',
    'post_agent_run',
    'pre_cms_write',
    'post_cms_write',
    'pre_final_report',
    'feedback_schedule',
    'learning_loop'
  )),
  severity text NOT NULL CHECK (severity IN ('blocking', 'warning', 'audit_only')),
  enforce_mode text NOT NULL CHECK (enforce_mode IN ('hard_block', 'soft_warn', 'audit_only')),
  condition_fn text NOT NULL,
  failure_state text,
  action_on_fail jsonb NOT NULL DEFAULT '[]'::jsonb,
  required_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  rule_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (guardrail_id, rule_version)
);

CREATE TABLE IF NOT EXISTS seo_os.guardrail_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  result_id uuid NOT NULL,
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  task_ref text NOT NULL,
  agent_run_id uuid REFERENCES seo_os.agent_runs(id) ON DELETE SET NULL,
  workflow_event_id uuid REFERENCES seo_os.workflow_events(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  checked_at timestamptz NOT NULL DEFAULT now(),
  stage text NOT NULL CHECK (stage IN (
    'pre_dispatch',
    'post_agent_run',
    'pre_cms_write',
    'post_cms_write',
    'pre_final_report',
    'feedback_schedule',
    'learning_loop'
  )),
  status text NOT NULL CHECK (status IN ('passed', 'failed', 'warning')),
  ok boolean NOT NULL,
  next_allowed boolean NOT NULL DEFAULT false,
  failure_state text,
  failed_guardrails text[] NOT NULL DEFAULT ARRAY[]::text[],
  checked_count integer NOT NULL DEFAULT 0,
  passed_count integer NOT NULL DEFAULT 0,
  failed_count integer NOT NULL DEFAULT 0,
  warning_count integer NOT NULL DEFAULT 0,
  context_sha256 text,
  context_path text,
  result_path text,
  source text NOT NULL DEFAULT 'seo-guardrail',
  local_only boolean NOT NULL DEFAULT true,
  production_side_effect boolean NOT NULL DEFAULT false,
  secret_redacted boolean NOT NULL DEFAULT true,
  result_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (result_id),
  CHECK (production_side_effect = false)
);

CREATE INDEX IF NOT EXISTS idx_guardrail_results_task ON seo_os.guardrail_results(task_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_results_task_ref ON seo_os.guardrail_results(task_ref, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_results_stage ON seo_os.guardrail_results(stage, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_results_status ON seo_os.guardrail_results(status, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_results_failure_state ON seo_os.guardrail_results(failure_state) WHERE failure_state IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_guardrail_results_result_json ON seo_os.guardrail_results USING gin (result_json);

CREATE TABLE IF NOT EXISTS seo_os.guardrail_result_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  guardrail_result_id uuid NOT NULL REFERENCES seo_os.guardrail_results(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  guardrail_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('passed', 'failed', 'warning')),
  severity text CHECK (severity IN ('blocking', 'warning', 'audit_only')),
  enforce_mode text CHECK (enforce_mode IN ('hard_block', 'soft_warn', 'audit_only')),
  failure_state text,
  reason text,
  missing_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  action_on_fail jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  check_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_guardrail_result_checks_result ON seo_os.guardrail_result_checks(guardrail_result_id);
CREATE INDEX IF NOT EXISTS idx_guardrail_result_checks_guardrail ON seo_os.guardrail_result_checks(guardrail_id, status);
CREATE INDEX IF NOT EXISTS idx_guardrail_result_checks_failure_state ON seo_os.guardrail_result_checks(failure_state) WHERE failure_state IS NOT NULL;

COMMIT;
