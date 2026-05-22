# Ohya Hermes Swarm Roster

更新日期：2026-05-02

## 目的

這份文件把 `/Users/garyyang/clients/ohya` 既有 9 個 Hermes profiles 接到 Hermes Kanban / Swarm 的分工語意。它不取代 coordinator 原本的 subprocess chain；用途是讓長任務、多人分工、有依賴、有 review gate 的工作可以被 durable board 追蹤。

## Kanban board 位置與執行邊界

Ohya 的 profiles 實體在：

```text
/Users/garyyang/clients/ohya/profiles/<profile>/
```

因此 Kanban CLI 必須用 client root 作為 `HERMES_HOME`，才會讓 `hermes -p <assignee>` 正確解析到 Ohya worker profiles：

```bash
export HERMES_HOME=/Users/garyyang/clients/ohya
/Users/garyyang/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main kanban stats
```

注意：`ohya-coordinator` Telegram gateway 目前為了 ByteRover 隔離使用 profile-local `HERMES_HOME=/Users/garyyang/clients/ohya/profiles/coordinator`。所以正式 Swarm 任務不要依賴 coordinator gateway 的 embedded dispatcher 自動撿 client-root board；應由 coordinator 明確呼叫 client-root `hermes kanban dispatch`，或未來另建 dedicated dispatcher。不要為了 Swarm 直接把現有 Telegram gateway 改回 client root，避免混 memory。

## Profile / role 對應

| Profile | Swarm role | 適合任務 | 預設 workspace |
|---|---|---|---|
| `coordinator` | orchestrator / Telegram 入口 | 拆任務、建 graph、追蹤、彙整回報 | 不直接做 worker task |
| `topic-researcher` | research worker | 主題研究、競品、AEO/FAQ、SERP intent | `dir:/Users/garyyang/workspace/ohya` |
| `outline-planner` | planning worker | H2/H3 結構、FAQ、內連規劃 | `dir:/Users/garyyang/workspace/ohya` |
| `writer` | drafting worker | 4000+ 字文章、段落重寫、客戶版草稿 | `dir:/Users/garyyang/workspace/ohya` |
| `link-finder` | citation/link validation worker | EXT_LINK 解析、HEAD check、外連替換 | `dir:/Users/garyyang/workspace/ohya` |
| `media-asset-generator` | media asset worker | hero/OG 圖規格、prompt、upload-ready package | `dir:/Users/garyyang/workspace/ohya` |
| `article-editor` | QA / pre-publish audit worker | 舊文診斷、pre-publish audit、regression review | `dir:/Users/garyyang/workspace/ohya` |
| `seo-graph` | graph/query worker | Neo4j Cypher、內連、topic cluster | `dir:/Users/garyyang/clients/ohya` |
| `cms-draft-executor` | CMS executor with gates | Payload draft、approval-gated correction、publish gate | `dir:/Users/garyyang/Desktop/ohya-payload` 或 repo 實際位置 |

## 新文章 Swarm graph

```text
T1 topic-researcher       research topic / SERP / competitors
  ↓
T2 outline-planner        outline + FAQ + angle
  ↓
T3 writer                 draft article
  ↓
T4 link-finder            resolve EXT_LINK + verify sources
  ↓
T5 media-asset-generator  hero / OG package
  ↓
T6 article-editor         pre-publish audit
  ↓
T7 cms-draft-executor     CMS draft only; publish waits for Gary approval
```

## 舊文優化 Swarm graph

```text
T1 article-editor         audit + fix queue
  ↓
T2 seo-graph              internal link / graph relationship suggestions
  ↓
T3 writer or link-finder  execute content/link fixes into artifact, not production
  ↓
T4 article-editor         regression audit
  ↓
T5 cms-draft-executor     draft/correction gate; no direct publish write
```

## 固定 guardrails

- 不動 `~/.hermes/hermes-agent/` source；Hermes 升級走 `hermes upgrade`。
- Published Payload content 的寫入必須走 draft / approval gate；不可直接改 live published post。
- `cms-draft-executor` 可以準備 draft / correction report；publish 需要 Gary 明確核准。
- Swarm test task 建完後若只是 dry-run，必須 archive，避免日後 dispatcher 被啟動時誤執行。
- 任務 body 必須包含：repo/workspace、輸入 artifact、輸出 artifact、驗證方式、禁止事項。

## 常用 CLI

```bash
export HERMES_HOME=/Users/garyyang/clients/ohya
PY=/Users/garyyang/.hermes/hermes-agent/venv/bin/python

$PY -m hermes_cli.main kanban init
$PY -m hermes_cli.main kanban create "title" --assignee topic-researcher --workspace dir:/Users/garyyang/workspace/ohya --body "..."
$PY -m hermes_cli.main kanban link <parent_id> <child_id>
$PY -m hermes_cli.main kanban dispatch --dry-run --max 10
$PY -m hermes_cli.main kanban list
$PY -m hermes_cli.main kanban show <task_id>
$PY -m hermes_cli.main kanban log <task_id>
$PY -m hermes_cli.main kanban runs <task_id>
```
