-- SEO Growth OS Phase 1.9A
-- Expand agent constraints to include cms-draft-executor.
-- Local/draft migration only until production/staging approval.

BEGIN;

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
    'system'
  )
);

COMMIT;
