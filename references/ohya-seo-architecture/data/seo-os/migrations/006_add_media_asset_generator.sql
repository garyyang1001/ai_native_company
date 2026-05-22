-- SEO Growth OS Phase 1.9B / media asset layer
-- Expand local OS constraints for media-asset-generator and media asset artifacts.
-- Local/draft migration only until production/staging approval.

BEGIN;

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
  'media_asset'
));

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
  'media_asset_report'
));

COMMIT;
