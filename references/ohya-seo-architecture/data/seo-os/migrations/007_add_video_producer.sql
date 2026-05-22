-- SEO Growth OS Phase 2.1 / video pipeline layer
-- Add video-producer agent + video task / artifact / event types.
-- Closes the loop: article cms_draft done → video_produce → YouTube upload.
-- Includes feedback / learning channel via video_feedback_received event.

BEGIN;

-- =============================================
-- tasks.type — add video_produce, video_replace
-- =============================================
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
  'video_replace'
));

-- =============================================
-- assigned_agent — add video-producer
-- =============================================
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
    'system'
  )
);

-- =============================================
-- artifacts.type — add 8 video artifact types
-- =============================================
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
  -- video pipeline artifacts
  'video_brief',
  'video_composition_html',
  'video_audio',
  'video_mp4',
  'video_thumbnail',
  'video_metadata',
  'video_caption',
  'video_upload_record'
));

-- =============================================
-- workflow_events.event_type — add 5 video events
-- =============================================
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
    -- video pipeline events
    'video_brief_created',
    'video_audio_synthesized',
    'video_rendered',
    'video_uploaded',
    'video_replaced',
    'video_feedback_received'
  )
);

COMMIT;
