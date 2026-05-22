-- Ohya SEO Growth OS content growth constraints expansion v1
-- Draft/local migration only. Do not run against production without Gary approval.
-- Purpose: support full Content Growth OS after Phase 1.5:
-- Discovery → New Article Production → Pre-publish Audit → CMS Draft/Preview → Feedback.

BEGIN;

-- tasks.type: add opportunity / pre-publish / CMS draft / preview workflow states.
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
  'publish_checklist'
));

-- artifacts.type: add opportunity queue, CMS draft/preview, pre-publish audit, and clearer scan report types.
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
  'publish_checklist'
));

-- workflow_events.event_type: support explicit next-task and content production events.
ALTER TABLE seo_os.workflow_events DROP CONSTRAINT IF EXISTS workflow_events_event_type_check;
ALTER TABLE seo_os.workflow_events ADD CONSTRAINT workflow_events_event_type_check CHECK (event_type IN (
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
  'feedback_task_created'
));

-- article_lifecycle.state: support new-article pipeline states.
ALTER TABLE seo_os.article_lifecycle DROP CONSTRAINT IF EXISTS article_lifecycle_state_check;
ALTER TABLE seo_os.article_lifecycle ADD CONSTRAINT article_lifecycle_state_check CHECK (state IN (
  'draft',
  'published',
  'monitored',
  'refresh_needed',
  'updating',
  'awaiting_approval',
  'merged',
  'redirected',
  'retired',
  'archived',
  'opportunity',
  'researching',
  'outlined',
  'drafting',
  'link_verified',
  'pre_publish_auditing',
  'cms_draft_ready',
  'preview_ready',
  'awaiting_publish_approval',
  'monitoring'
));

-- article_lifecycle.next_action: support content growth follow-up actions.
ALTER TABLE seo_os.article_lifecycle DROP CONSTRAINT IF EXISTS article_lifecycle_next_action_check;
ALTER TABLE seo_os.article_lifecycle ADD CONSTRAINT article_lifecycle_next_action_check CHECK (
  next_action IS NULL OR next_action IN (
    'monitor',
    'audit',
    'refresh',
    'merge',
    'redirect',
    'internal_link_fix',
    'publish',
    'no_action',
    'research',
    'outline',
    'write',
    'link_fix',
    'pre_publish_audit',
    'cms_draft',
    'preview_verification',
    'performance_review'
  )
);

-- approvals.action: add CMS draft / preview gates while keeping production actions explicit.
ALTER TABLE seo_os.approvals DROP CONSTRAINT IF EXISTS approvals_action_check;
ALTER TABLE seo_os.approvals ADD CONSTRAINT approvals_action_check CHECK (action IN (
  'publish',
  'update_article',
  'merge_articles',
  'add_redirect',
  'send_client_report',
  'change_title',
  'change_meta',
  'delete_article',
  'run_migration',
  'deploy',
  'create_cms_draft',
  'update_cms_draft',
  'verify_preview',
  'approve_pre_publish_audit'
));

-- decisions.scope: add opportunity / CMS draft / preview scopes.
ALTER TABLE seo_os.decisions DROP CONSTRAINT IF EXISTS decisions_scope_check;
ALTER TABLE seo_os.decisions ADD CONSTRAINT decisions_scope_check CHECK (scope IN (
  'topic',
  'article',
  'workflow',
  'client',
  'offer',
  'agent_output',
  'publishing',
  'internal_link',
  'merge',
  'schema',
  'content_opportunity',
  'cms_draft',
  'preview',
  'performance_feedback'
));

COMMIT;
