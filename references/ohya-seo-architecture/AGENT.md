# AGENT.md — 好事發生數位 操作手冊（Claude session 用）

> 這份文件的讀者是「下一個接手這個專案的 Claude session」。
> 讀完就能無需 Gary 額外解釋直接動工。人看的專案介紹在 [`README.md`](./README.md)。

---

## TL;DR（先記這 5 條）

1. **這個專案是什麼**：好事發生數位是 `ohya.co`（109 篇 SEO 文章）的多 agent 生產系統，跑在 [Hermes framework](https://github.com/NousResearch/hermes-agent) 上，目前有 **10 個 specialized agent / profile**；Telegram 入口是 coordinator，其他 worker 由 coordinator 或 CLI/Swarm 派工。
2. **專案根目錄是 `~/clients/ohya/`**。如果你的 cwd 不對，`cd ~/clients/ohya` 再繼續。
3. **Hermes 本體在 `~/.hermes/hermes-agent/`，不要動 Hermes source code**。ohya 客製全部在 profiles / skills / bin 裡。
4. **官網正式 repo 是 [`garyyang1001/ohya-payload`](https://github.com/garyyang1001/ohya-payload)，本機入口在 `/Users/garyyang/Desktop/ohya-payload`（目前是 symlink 到外接碟 archive）**。這是 Payload 3 + Next.js + PostgreSQL，部署在 Zeabur；公開站 `https://ohya.co` 同時提供 `/admin` 與 `/api/posts`。不要再把 `/Users/garyyang/Desktop/ohya-AI` 當正式官網 repo。
5. **一律繁中台灣用語**。每個 agent 的 SOUL.md 都寫死「NEVER use English」。

---

## 專案路徑地圖

```
~/.hermes/hermes-agent/                  Hermes framework (不改)
  ├── venv/bin/python                    Python 3.11 venv (所有 agent 共用)
  ├── hermes_cli/main.py                 CLI entry: `hermes --profile X chat ...`
  ├── gateway/                           多平台 gateway (telegram / discord / ...)
  ├── agent/                             system prompt / compression / caching
  ├── tools/                             tool registry + 內建工具
  ├── AGENTS.md                          Hermes 官方開發指南
  └── README.md                          Hermes 官方 README

~/clients/ohya/                          ★ 專案根目錄 (HERMES_HOME 指向這裡)
  ├── README.md                          人看的專案介紹
  ├── AGENT.md                           ← 你正在讀的
  ├── CLAUDE.md                          auto-load AGENT.md
  ├── profiles/
  │   ├── coordinator/                   Telegram bot 入口
  │   ├── article-editor/                舊文診斷
  │   ├── topic-researcher/              主題研究
  │   ├── outline-planner/               大綱規劃
  │   ├── writer/                        文章撰寫
  │   ├── link-finder/                   外連驗證
  │   ├── seo-graph/                     知識圖譜查詢
  │   ├── cms-draft-executor/            Payload CMS draft / publish gate executor
  │   ├── media-asset-generator/         Hero / OG / media asset 準備
  │   └── higgsfield-video-producer/    Higgsfield MCP / AI 影片製作（Telegram bot）
  ├── bin/                               共用 helper script
  │   ├── get-article                    Payload API 抓文章
  │   ├── read-page                      抓任意網頁全文
  │   ├── gsc-query                      GSC API (28/90 天)
  │   ├── md-to-gdoc                     md → HTML → Google Doc
  │   ├── neo4j-query                    Cypher 查詢
  │   ├── scrape-article                 Payload → Neo4j
  │   ├── sync-neo4j                     增量更新 Neo4j
  │   ├── verify-url                     HEAD check
  │   └── web-search                     DuckDuckGo 搜尋
  ├── data/
  │   └── facts-registry.json            官方數字登錄冊
  └── credentials/
      ├── gsc-credentials.json           OAuth client
      └── gsc-token.json                 OAuth token (--auth 後產生)

~/workspace/ohya/                        agent 產出
  ├── {date}-{slug}/                     新文章 pipeline
  │   ├── 00-research.md / .json
  │   ├── 01-outline.md / .json
  │   ├── 02-draft.md                    writer 產 (含 EXT_LINK placeholder)
  │   ├── 03-final.md                    link-finder 解完 → 可發布
  │   └── competitors/*.txt
  └── audits/{date}-{slug}/              article-editor 產出
      ├── audit-report.md                人看報告
      ├── patch-plan.json                結構化 patch
      ├── fix-queue.json                 派工清單 (coordinator chain 讀)
      ├── article-snapshot.md
      ├── gsc-raw.json
      ├── competitors-snapshot/
      └── _trace/                        一次性 Python 腳本 / debug log

/Users/garyyang/Desktop/ohya-payload/     ★ ohya.co 正式官網 / Payload CMS repo（symlink 到外接碟）
  ├── README.md                            Payload/Zeabur/collection 說明
  ├── docs/DEPLOYMENT.md                   Zeabur 部署 runbook
  ├── src/payload.config.ts                Payload 主設定
  ├── src/collections/Posts/index.ts       Posts collection；drafts + versions enabled
  ├── src/app/(frontend)/                  公開網站頁面與服務頁文案
  ├── src/app/(frontend)/portfolio/        作品集頁（page.tsx + content.ts）
  ├── src/app/(payload)/admin              Payload admin `/admin`
  └── src/lib/payload-api.ts               前台讀 `/api/*`

/Users/garyyang/clients/ohya/credentials/
  └── zeabur-api-key                       Zeabur Server API key（0600；不要印值）

/Users/garyyang/.local/bin/zeabur          Zeabur CLI 0.15.0（已登入）
  ├── project untitled-1                   ID: 69d34c7e18daef21c6040fb0
  ├── environment                          ID: 69d34c7e474db8a99d6dccd9
  ├── service ohya                         ID: 69d4598f327f44a3cdec195e
  └── domain ohya.co                       status: PROVISIONED

~/Library/LaunchAgents/com.hermes.gateway.ohya-coordinator.plist  coordinator Telegram gateway（其他 8 個通常是 subprocess/CLI worker）
~/Library/Logs/hermes-gateway-{name}.{log,err.log}
```

---

## Profile 內部結構（每個 agent 都長一樣）

```
profiles/<name>/
├── SOUL.md                              身份 + 鐵則 (自動注入 system prompt)
├── config.yaml                          Hermes per-profile 設定
├── .env                                 TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USERS
├── skills/content/ohya-<name>/
│   └── SKILL.md                         ← ★ 工作流程定義 (loaded on demand)
├── memories/
│   ├── MEMORY.md                        agent 長期記憶 (Hermes 自動 curate + nudge)
│   └── USER.md                          user profile (Gary)
├── sessions/                            FTS5 conversation history (過去對話可 search)
├── tasks/ (只有 coordinator)            active.json + history/{task_id}.json
├── gateway.pid + gateway_state.json     launchd 管理用
├── state.db + state.db-{shm,wal}        SQLite session store
└── logs/                                launchd stdout/err log (跟 ~/Library/Logs 不同)
```

---

## 10 個 Agent / Profile 速查

| Agent | 核心功能 | 常見輸出 |
|---|---|---|
| **coordinator** | 意圖分類 → 派工 → 整合回報 | Telegram 摘要 |
| **article-editor** | 6+1 檢查 → audit-report/patch-plan/fix-queue | `~/workspace/ohya/audits/` |
| **topic-researcher** | 主題 → 競品 → 關鍵字 → AEO | `00-research.md/.json` |
| **outline-planner** | 讀研究 → H2/H3 結構 + FAQ | `01-outline.md/.json` |
| **writer** | 讀大綱 → 4000+ 字文章 | `02-draft.md` |
| **link-finder** | 解 EXT_LINK + HEAD check | `03-final.md` |
| **seo-graph** | Cypher 查詢 Neo4j | 直接回覆 |
| **cms-draft-executor** | Payload CMS draft / publish gate / published-content correction executor | CMS draft / approval-gated write report |
| **media-asset-generator** | 文章 hero / OG / media asset 準備 | media spec / asset prompt / upload-ready package |
| **higgsfield-video-producer** | Higgsfield MCP / AI 影片分鏡與生成 | video prompt pack / generated clips / QA package |

---

## 與 StudyCentral/Tazimac 的關鍵差異

| 項目 | StudyCentral/Tazimac | 好事發生數位 (ohya) |
|---|---|---|
| CMS | WordPress | **Payload CMS (Next.js)** |
| API | WP REST API | **Payload REST API** `/api/posts` |
| 認證 | WP Application Password | **公開 API**（讀取不需認證） |
| 託管 | 虛擬主機 | **Zeabur** |
| 產業 | 留學/壓鑄 | **AI 顧問 / 數位行銷** |
| Neo4j Port | 7687/7688 | **7690** |
| 文章 URL 格式 | `/{slug}/` | **`/blog/{slug}`** |

---

## Coordinator 派工機制

跟 StudyCentral 完全相同的 subprocess delegate pattern：

1. **Step 0 讀 `tasks/active.json`** 判斷模式（新請求 / awaiting_checkpoint / running）
2. **Step 1 意圖分類** 成 12 種之一（`audit / query / research / outline / write / link_fix / pipeline_new_article / chain_audit_fix / status / cancel / ambiguous / out_of_scope`）
3. **Step 2 `ambiguous` / `out_of_scope` → 問 / 拒絕，不派工**
4. **Step 3 寫 active.json + subprocess 派工**：
   ```bash
   HERMES_HOME=/Users/garyyang/clients/ohya \
     /Users/garyyang/.hermes/hermes-agent/venv/bin/python \
     -m hermes_cli.main --profile <target> chat --max-turns 120 --yolo \
     -q "<prompt>" 2>&1
   ```
   - ≤ 600s → `terminal` foreground
   - \> 600s → `terminal(background=true)` + `process(wait/poll)`
5. **Step 4 Chain**：`chain_audit_fix` 跑完 article-editor 後讀 `fix-queue.json`，逐條派給 link-finder/writer
6. **Step 5 整合回 Gary**：結構化 Telegram 摘要（< 3500 字元）

---

## Hermes Swarm / Kanban 模式（長任務用）

Ohya 也支援 Hermes Kanban / Swarm，但它是「長任務 durable board」，不是所有請求都要用。短任務仍走上面的 coordinator subprocess chain。

### 什麼時候用 Swarm

- 新文章從 research → outline → draft → link → media → audit → CMS draft 的完整流程
- 舊文 audit 後需要 writer / link-finder / seo-graph / cms-draft-executor 多 profile 接力
- 任務超過 15 分鐘、要中途回來查狀態、或需要明確 parent/child 依賴
- 需要 reviewer / approval gate，不希望單一 worker 自己說自己完成

### Board 與 HERMES_HOME

Ohya Swarm CLI 一律用 client root：

```bash
export HERMES_HOME=/Users/garyyang/clients/ohya
/Users/garyyang/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main kanban stats
```

原因：Ohya worker profiles 在 `/Users/garyyang/clients/ohya/profiles/<profile>`。若用 coordinator profile-local HERMES_HOME，Kanban board 會落在 `profiles/coordinator/kanban.db`，不適合跨 9 個 Ohya profiles 派工。

詳細 roster / task graph 見：

- `/Users/garyyang/clients/ohya/docs/swarm-roster.md`
- `/Users/garyyang/clients/ohya/kanban/templates/new-article-swarm.template.md`
- `/Users/garyyang/clients/ohya/kanban/templates/audit-swarm.template.md`

### Swarm role 對應

```text
coordinator              orchestrator / Telegram 入口
topic-researcher          research worker
outline-planner           planning worker
writer                    drafting worker
link-finder               citation/link validation worker
media-asset-generator     media asset worker
higgsfield-video-producer  AI video / Higgsfield MCP worker
article-editor            QA / pre-publish audit worker
seo-graph                 graph/query worker
cms-draft-executor        CMS draft / approval-gated executor
```

### Safety

- Dry-run 測試任務完成後必須 archive，避免未來 dispatcher 啟動後誤執行。
- `cms-draft-executor` 不可 publish；publish 需要 Gary 明確 approval。
- 不要為了 Swarm 直接改現有 `ohya-coordinator` Telegram gateway 的 profile-local HERMES_HOME；那會影響 ByteRover 隔離。需要自動 dispatcher 時，另建 dedicated dispatcher / 或由 coordinator 明確呼叫 client-root `kanban dispatch`。

---

## 要你避開的坑（踩過會很痛）

### 1. ohya.co 不是 WordPress
不要嘗試用 WP REST API、不要找 `wp-rest.json`、不要用 Application Password。ohya.co 用的是 Next.js + Payload CMS，API 是 `/api/posts`。

### 2. Payload API 是公開的
讀取 `/api/posts` 不需要 auth token。直接 GET 就好。

### 3. 文章 URL 格式是 `/blog/{slug}`
不是 `/{slug}/`。所有 bin/ scripts 和 agent prompt 都要用 `/blog/` prefix。

### 4. content_html 欄位
從 WordPress 遷移保留的 HTML，不是 Payload 原生的 Lexical richText 格式。抓文章內容時用 `content_html` 欄位。

### 5. mtime 陷阱
Coordinator subprocess timeout 後不能只檢查「audit-report.md 存不存在」判斷有無產出，因為同一資料夾可能有歷史 audit 的殘留舊檔。正確作法：

```bash
TASK_START_EPOCH=$(python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('$TASK_STARTED_AT'.replace('Z','+00:00')).timestamp()))")
for f in audit-report.md patch-plan.json fix-queue.json; do
  mtime=$(stat -f "%m" "$AUDIT_DIR/$f")
  [ "$mtime" -ge "$TASK_START_EPOCH" ] && echo fresh || echo stale
done
```

三個檔案都 fresh 才算本次產出。

### 6. fix-queue.json 必須回寫 status
Chain mode 下每個子 task 成功後要回寫 `status: "done"` + `completed_at` + `output_files`。沒回寫 → 下次接 chain 會重複執行已完成的 task。

### 7. 一次一個 agent，不要並行 dispatch
State 會亂。coordinator 的 `tasks/active.json` 一次只放一個 task。

### 8. Google Doc 推送 — tree art 會自動修
`md-to-gdoc` 的 `wrap_tree_art()` preprocess 會自動把 ASCII tree art 包成 `<pre><code>`，不需要手動處理。

### 9. `build_audit.py` 是一次性檔案
article-editor 每次跑 audit 可能會寫一個 `build_audit.py` 當 scratchpad，會被 `mv` 到 `_trace/`。不要當成穩定程式檔去維護。

### 10. 繁中台灣用語是鐵則
SOUL.md 寫死 `NEVER use English`。如果 agent 被觀察到用英文回，要檢查 SOUL.md 和 SKILL.md 是否被誤改。

---

## 常見工作流程

### Gary 要你做 audit

1. 確認 URL 格式正常（`https://ohya.co/blog/{slug}`）
2. Telegram 途徑：對 coordinator bot 傳「審 <URL>」→ coordinator 派工
3. CLI 途徑（debug 用）：
   ```bash
   HERMES_HOME=/Users/garyyang/clients/ohya \
     ~/.hermes/hermes-agent/venv/bin/python \
     -m hermes_cli.main --profile article-editor chat --yolo \
     -q "診斷 https://ohya.co/blog/xxx"
   ```
4. 預期耗時 5-13 分鐘
5. 產出位置：`~/workspace/ohya/audits/{YYYY-MM-DD}-{slug}/`

### Gary 要你 debug 某個 agent 卡住

```bash
# 1. 看 launchd 是否在跑
launchctl list | grep hermes

# 2. 看最近的 stderr
tail -100 ~/Library/Logs/hermes-gateway-<name>.err.log

# 3. 看 coordinator 當前 active task
cat ~/clients/ohya/profiles/coordinator/tasks/active.json

# 4. 手動殺
launchctl unload ~/Library/LaunchAgents/com.hermes.gateway.<name>.plist
launchctl load ~/Library/LaunchAgents/com.hermes.gateway.<name>.plist

# 5. 清卡住的 active.json
mv ~/clients/ohya/profiles/coordinator/tasks/active.json \
   ~/clients/ohya/profiles/coordinator/tasks/active.json.bak-$(date +%s)
```

### Gary 要你看上次跑了什麼

```bash
# 最近 audit
ls -lt ~/workspace/ohya/audits/ | head

# 最近新文章 pipeline
ls -lt ~/workspace/ohya/ | head

# coordinator task 歷史
ls -lt ~/clients/ohya/profiles/coordinator/tasks/history/ | head
```

### Gary 要你更新 SKILL.md

SKILL.md 是 **load-on-demand**，不需要重啟 gateway，下次 agent 被呼叫就會重讀。放心改。但注意：

- 改完用 grep 確認關鍵 step 編號沒斷
- 避免插入新 step 時打亂順序
- 改大改動前先看 `~/clients/ohya/profiles/<agent>/.skills_prompt_snapshot.json` 的 size

### Gary 要你改 bin/ helper

```bash
# 改完沒有 reload 步驟，下次 agent subprocess 呼叫就生效
# 驗證：
~/clients/ohya/bin/<helper> --help
```

---

## 關鍵設計決策（歷史背景，別再質疑）

- **用 Payload CMS 而非 WordPress**：ohya.co 本身就是用 Next.js + Payload 建的，不需要另外架 WP。
- **共用 OAuth token**：GSC + Drive 用同一個 OAuth token（兩個 scope 合併），存在 `credentials/gsc-token.json`。
- **Neo4j 獨立 container**：ohya-neo4j at port 7477(HTTP)/7690(Bolt)，跟 StudyCentral(7474/7687) 和 Tazimac(7475/7688) 分開。
- **bin/ scripts 用 Payload API**：`get-article`、`scrape-article` 全部改用 `/api/posts` endpoint。
- **coordinator 用 subprocess delegate 而非 bot-to-bot**：跟 StudyCentral 同理，Plan A 需要改 Hermes `telegram.py`，engineering-to-value 不划算。
- **audit 產出 3 個檔案（report/patch-plan/fix-queue）**：report 人看、patch-plan agent 讀、fix-queue chain 派工。三者職責分離。
- **新文章 pipeline 是 checkpoint 模式，chain audit-fix 是全自動**：新文章成本高，每階段等 Gary 確認；修舊文風險低，全自動跑到底。
- **tree art 格式修復在 md-to-gdoc layer**：遵循「code > prompt for deterministic tasks」原則。

---

## 文章主題涵蓋範圍

ohya.co 的 109 篇文章主要覆蓋以下主題：

- **AI 顧問服務**：企業 AI 導入、AI 策略規劃
- **OpenClaw**：自家 AI 產品相關
- **n8n 自動化**：工作流自動化、API 串接
- **SEO**：搜尋引擎優化、內容策略
- **數位行銷**：社群經營、廣告投放、品牌策略
- **自由工作者**：接案心得、遠端工作、個人品牌

---

## 當你迷路時

1. **不確定 agent 能幹什麼** → 讀該 profile 的 `SOUL.md`（50 行以內，快）
2. **不確定 agent 怎麼做事** → 讀該 profile 的 `skills/content/*/SKILL.md`
3. **不確定 agent 記得什麼** → 讀該 profile 的 `memories/MEMORY.md`
4. **不確定 Hermes 怎麼跑** → 讀 `~/.hermes/hermes-agent/AGENTS.md` 和 `README.md`
5. **不確定最近發生什麼** → `ls -lt ~/workspace/ohya/`

迷太久？直接問 Gary。他知道。
