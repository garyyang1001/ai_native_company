-- Ohya SEO Growth OS lifecycle / decisions / approvals / performance v1
-- Draft only. Do not run against production without Gary approval.

CREATE TABLE IF NOT EXISTS seo_os.article_lifecycle (
  slug text PRIMARY KEY,
  url text,
  payload_post_id text,
  neo4j_article_id text,
  state text NOT NULL CHECK (state IN ('draft', 'published', 'monitored', 'refresh_needed', 'updating', 'awaiting_approval', 'merged', 'redirected', 'retired', 'archived')),
  last_audit_at timestamptz,
  last_publish_at timestamptz,
  last_performance_snapshot_at timestamptz,
  current_owner_type text CHECK (current_owner_type IS NULL OR current_owner_type IN ('gary', 'consultant', 'supervisor', 'agent', 'system')),
  current_owner_id text,
  next_action text CHECK (next_action IS NULL OR next_action IN ('monitor', 'audit', 'refresh', 'merge', 'redirect', 'internal_link_fix', 'publish', 'no_action')),
  priority_score numeric(8,3),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_article_lifecycle_state ON seo_os.article_lifecycle(state);
CREATE INDEX IF NOT EXISTS idx_article_lifecycle_next_action ON seo_os.article_lifecycle(next_action);
CREATE INDEX IF NOT EXISTS idx_article_lifecycle_priority ON seo_os.article_lifecycle(priority_score DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS seo_os.decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  decision_maker_type text NOT NULL CHECK (decision_maker_type IN ('gary', 'consultant', 'supervisor', 'agent', 'system')),
  decision_maker_id text,
  scope text NOT NULL CHECK (scope IN ('topic', 'article', 'workflow', 'client', 'offer', 'agent_output', 'publishing', 'internal_link', 'merge', 'schema')),
  slug text,
  decision text NOT NULL CHECK (decision IN ('approve', 'reject', 'rewrite', 'merge', 'redirect', 'no_action', 'change_positioning', 'needs_human_review', 'archive', 'supersede')),
  reason text,
  source_message text,
  applies_to_future boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_decisions_slug ON seo_os.decisions(slug);
CREATE INDEX IF NOT EXISTS idx_decisions_scope ON seo_os.decisions(scope);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON seo_os.decisions(created_at DESC);

CREATE TABLE IF NOT EXISTS seo_os.approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES seo_os.tasks(id) ON DELETE SET NULL,
  decision_id uuid REFERENCES seo_os.decisions(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz,
  action text NOT NULL CHECK (action IN ('publish', 'update_article', 'merge_articles', 'add_redirect', 'send_client_report', 'change_title', 'change_meta', 'delete_article', 'run_migration', 'deploy')),
  risk_level text NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
  requested_by text NOT NULL,
  required_approver_type text NOT NULL CHECK (required_approver_type IN ('gary', 'consultant', 'supervisor', 'admin')),
  required_approver_id text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
  approval_message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON seo_os.approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON seo_os.approvals(task_id);
CREATE INDEX IF NOT EXISTS idx_approvals_created ON seo_os.approvals(created_at DESC);

CREATE TABLE IF NOT EXISTS seo_os.performance_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text,
  url text,
  snapshot_date date NOT NULL,
  period_days integer NOT NULL,
  clicks integer,
  impressions integer,
  ctr numeric(8,5),
  avg_position numeric(8,3),
  clicks_delta integer,
  impressions_delta integer,
  position_delta numeric(8,3),
  bucket text CHECK (bucket IS NULL OR bucket IN ('healthy', 'decaying', 'almost_there', 'stale', 'zombie', 'unranked', 'new', 'needs_review')),
  priority_score numeric(8,3),
  source text NOT NULL DEFAULT 'gsc' CHECK (source IN ('gsc', 'ga4', 'manual', 'import', 'priority_scan')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (slug, snapshot_date, period_days, source)
);

CREATE INDEX IF NOT EXISTS idx_performance_slug_date ON seo_os.performance_snapshots(slug, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_performance_bucket ON seo_os.performance_snapshots(bucket);
CREATE INDEX IF NOT EXISTS idx_performance_priority ON seo_os.performance_snapshots(priority_score DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS seo_os.weekly_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  week_start date NOT NULL,
  week_end date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text,
  title text NOT NULL,
  summary text,
  markdown_path text,
  google_doc_url text,
  task_count integer,
  completed_task_count integer,
  failed_task_count integer,
  approval_pending_count integer,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (week_start, week_end)
);
