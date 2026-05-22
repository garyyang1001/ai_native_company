-- Ohya SEO Growth OS new article approval actions v1
-- Draft/local migration only. Do not run against production without Gary approval.
-- Purpose: make Phase 1.8 topic approval and research continuation gates first-class records.

BEGIN;

-- approvals.action: add explicit topic and research continuation gates.
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
  'approve_pre_publish_audit',
  'topic_approval',
  'continue_after_research'
));

-- decisions.decision: add hold and refresh_existing_instead outcomes for topic gate.
ALTER TABLE seo_os.decisions DROP CONSTRAINT IF EXISTS decisions_decision_check;
ALTER TABLE seo_os.decisions ADD CONSTRAINT decisions_decision_check CHECK (decision IN (
  'approve',
  'reject',
  'rewrite',
  'merge',
  'redirect',
  'no_action',
  'change_positioning',
  'needs_human_review',
  'archive',
  'supersede',
  'hold',
  'refresh_existing_instead'
));

COMMIT;
