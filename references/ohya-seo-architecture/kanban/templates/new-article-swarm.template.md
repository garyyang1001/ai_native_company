# Ohya Swarm Template — New Article Pipeline

用途：從主題到 Payload CMS draft 的完整多 agent 任務圖。

## 變數

- topic：`<文章主題>`
- slug：`<YYYY-MM-DD-slug>`
- workspace：`/Users/garyyang/workspace/ohya/<slug>`
- tenant：`ohya-new-article-<slug>`

## 建議任務圖

1. `topic-researcher` — research topic / SERP / competitors
2. `outline-planner` — outline + FAQ + internal-link candidates
3. `writer` — draft article from outline
4. `link-finder` — resolve EXT_LINK + verify sources
5. `media-asset-generator` — hero/OG image package
6. `article-editor` — pre-publish audit
7. `cms-draft-executor` — create CMS draft only; publish waits for Gary approval

## 建 task 範例

```bash
export HERMES_HOME=/Users/garyyang/clients/ohya
PY=/Users/garyyang/.hermes/hermes-agent/venv/bin/python
TENANT="ohya-new-article-<slug>"
WS="dir:/Users/garyyang/workspace/ohya/<slug>"

T1=$($PY -m hermes_cli.main kanban create "[Ohya] Research: <topic>" --tenant "$TENANT" --assignee topic-researcher --workspace "$WS" --body "Research <topic>. Output 00-research.md and 00-research.json. No CMS writes." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T2=$($PY -m hermes_cli.main kanban create "[Ohya] Outline: <slug>" --tenant "$TENANT" --assignee outline-planner --workspace "$WS" --parent "$T1" --body "Read T1 output. Produce 01-outline.md/json. No CMS writes." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T3=$($PY -m hermes_cli.main kanban create "[Ohya] Draft: <slug>" --tenant "$TENANT" --assignee writer --workspace "$WS" --parent "$T2" --body "Read outline. Produce 02-draft.md. Keep EXT_LINK placeholders for link-finder. No CMS writes." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T4=$($PY -m hermes_cli.main kanban create "[Ohya] Link validation: <slug>" --tenant "$TENANT" --assignee link-finder --workspace "$WS" --parent "$T3" --body "Resolve EXT_LINK placeholders and verify URLs. Produce 03-final.md. No CMS writes." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T5=$($PY -m hermes_cli.main kanban create "[Ohya] Media package: <slug>" --tenant "$TENANT" --assignee media-asset-generator --workspace "$WS" --parent "$T4" --body "Prepare hero/OG image spec and upload-ready assets. Do not upload/publish unless explicitly approved." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T6=$($PY -m hermes_cli.main kanban create "[Ohya] Pre-publish audit: <slug>" --tenant "$TENANT" --assignee article-editor --workspace "$WS" --parent "$T5" --body "Audit 03-final.md and media package. Produce prepublish-audit.md and fix queue. No CMS writes." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
T7=$($PY -m hermes_cli.main kanban create "[Ohya] CMS draft gate: <slug>" --tenant "$TENANT" --assignee cms-draft-executor --workspace "$WS" --parent "$T6" --body "Create Payload CMS draft only after checking required auth. Do not publish. Publish requires Gary approval." --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

$PY -m hermes_cli.main kanban dispatch --dry-run --max 10
```
