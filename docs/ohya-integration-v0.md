# OHYA 整合 v0 — 第一個跑通 Gary kernel 的客戶

**對應路線**：`docs/hermes-integration-assessment-v0.md` 推薦的路線 A
**目標客戶**：OHYA / 好事發生數位（Gary 確認兩者同一法人）
**選此客戶理由**：是自家事業，做壞了不傷客戶；HermesRuntime 規模最大、事件最多樣
**狀態**：階段 0-2 已完成；階段 3 進行中

---

## 階段 0：砍掉舊版 ohya-seo-company（已完成 2026-05-24）

**動作**：把 `/Volumes/Hermes System/HermesArchive/Hermes-Archive/Desktop-archive-20260426/ohya-seo-company/`（37 MB、Paperclip + OpenClaw 7-agent 架構）改名為 `ohya-seo-company.deprecated-2026-05-24/`。

**為什麼軟刪除而不是 `rm -rf`**：
- 改名後任何引用會立刻爆錯，知道不該再用
- 過陣子真確定不需要再 rm 也來得及
- 可逆動作 vs 不可逆動作的權衡

如果未來確定要永久刪，Gary 一句話我直接 `rm -rf` 那個 .deprecated 目錄。

---

## 階段 1：建立 OHYA 專屬的 Gary kernel database（已完成 2026-05-24）

```bash
createdb ohya_kernel
KERNEL_DATABASE_URL='postgresql:///ohya_kernel' python3 -c "
from closed_loop_kernel.store import KernelStore
from closed_loop_kernel.sql_sandbox import SqlSandbox
store = KernelStore.from_url('postgresql:///ohya_kernel')
store.initialize()
SqlSandbox('postgresql:///ohya_kernel').ensure_role()
"
```

**結果**：
- 11 張表全建好（events / artifacts / policy_gates / attempt_lifecycle_events / attempts / decisions / tool_calls / failures / improvement_candidates / replays / approvals）
- `sandbox_runner` 低權限 PostgreSQL 角色已備
- `prevent_mutation` trigger 已掛在 6 張 append-only 表

**未來連線**：`KERNEL_DATABASE_URL=postgresql:///ohya_kernel`

---

## 階段 2：探勘 OHYA kanban.db 結構（已完成 2026-05-24）

**來源**：`/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/ohya/kanban.db`

### OHYA 既有 SQLite schema 摘要

| 表 | 用途 | 關鍵欄位 |
|---|---|---|
| `tasks` | 高層任務（kanban 卡片） | id, title, body, assignee, status, priority, **tenant**, idempotency_key, consecutive_failures |
| `task_runs` | 任務每次執行嘗試 | id, task_id, profile, **status** (running/done/blocked/crashed/timed_out/failed/released), **outcome**, error, summary, started_at, ended_at |
| `task_events` | 任務事件流 | id, task_id, run_id, kind (created/archived/linked/promoted/decomposed/spawned/claimed), payload |
| `task_comments` | 任務評論 | id, task_id, author, body |
| `task_links` | 任務依賴關係（parent-child） | parent_id, child_id |
| `kanban_notify_subs` | Telegram / 平台通知訂閱 | task_id, platform, chat_id, thread_id, notifier_profile |

### 實際資料樣本（從 OHYA kanban.db 直接 SELECT）

- tasks: status 分布 `archived=7, todo=6, ready=2, running=1`
- task_events: kind 分布 `created=16, archived=7, linked=5, promoted=3, decomposed=2, specified=1, spawned=1, claimed=1`
- tenant 範例：`ohya-swarm-dryrun-20260502`, `ohya-swarm-templates`

### ⚠️ 已知問題：kanban.db 部分損毀

讀 `task_runs` 時回報 `Error: stepping, database disk image is malformed (11)`。tasks 表本身可讀，但執行紀錄部分檔案頁面壞了。

**意涵**：
1. **EventReporter 要容錯** — 讀 task_runs / task_events 個別 row 時要 try/except，不能讓單一壞 row 中斷整個 sync
2. **Gary kernel 是新的 source of truth** — 一旦 EventReporter 跑起來，未來新事件主要存 ohya_kernel，kanban.db 慢慢退役
3. **要建議 Gary 把 kanban.db 跑一次完整性檢查**（`PRAGMA integrity_check`）並考慮 VACUUM / REINDEX

---

## 階段 2.5：OHYA kanban.db → Gary kernel 事件對映表

設計依據：
- OHYA `task_runs` 大致對應 Gary kernel `attempts`（一個 task_run = 一個 attempt）
- OHYA `task_events` 大致對應 Gary kernel `attempt_lifecycle_events` 與 `events`
- OHYA 沒有 `failures` / `improvement_candidates` / `replays` / `approvals` 概念 — 這些靠 Gary kernel 補

| OHYA 來源 | Gary kernel 目標 | 對映規則 |
|---|---|---|
| `tasks.tenant` | `attempts.input.tenant` + `events.payload.tenant` | 全部事件帶 tenant 標籤 |
| `tasks.id` | `attempts.input.kanban_task_id` | 保留原始連結 |
| `tasks.title` | `attempts.input.title` | |
| `task_runs.id` | `attempts.input.kanban_run_id` | 不直接當 attempt.id（attempt.id 是 UUID） |
| `task_runs.profile` | `tool_calls.tool_name` | profile 是哪個 agent 跑的 |
| `task_runs.status='running'` | `attempt_lifecycle_events(state='running')` | |
| `task_runs.status='done'` | `attempts(status='success')` + lifecycle `finished` | |
| `task_runs.status='crashed' / 'timed_out' / 'failed' / 'gave_up'` | `attempts(status='failed')` + `failures(status='open')` | 觸發後續修正案流程 |
| `task_runs.error` | `attempts.error_message` + `failures.context.error` | |
| `task_runs.summary` | `attempts.output.summary` | |
| `task_runs.metadata` | `attempts.output.metadata` (JSONB) | |
| `task_events.kind` | `events.event_type` (前綴 `ohya_kanban_`) | 例如 `ohya_kanban_created` |
| `task_events.payload` | `events.payload` (含原 payload + tenant) | |
| `task_runs.outcome='crashed'` | `failures.failure_type = 'crash'` | 用 outcome 做分類 |
| `task_runs.outcome='timed_out'` | `failures.failure_type = 'timeout'` | |
| `task_runs.outcome='spawn_failed'` | `failures.failure_type = 'spawn_failed'` | |
| `task_runs.outcome='gave_up'` | `failures.failure_type = 'gave_up'` | |

### Sync 策略

- **單向 sync**：kanban.db → ohya_kernel，**不反向寫**（kanban.db 由 HermesRuntime 主控，Gary kernel 不該干擾）
- **增量 sync**：用 `task_events.id` (auto-increment) 做 checkpoint，每次 sync 從上次的最高 id 之後繼續
- **Checkpoint 存哪**：ohya_kernel `events` 表新增一筆 `event_type='kanban_sync_checkpoint'`、`payload={last_event_id: N, last_sync_at: ...}`
- **冪等性**：用 `task_events.id` + `task_runs.id` 配 `attempts.input.kanban_run_id` 去重（避免同筆事件被重複寫進 ohya_kernel）
- **錯誤容忍**：單 row 解析或寫入失敗只 log，不中斷整個 sync 批次

---

## 階段 3：EventReporter 函式庫設計

放在 Gary kernel repo 的 `closed_loop_kernel/event_reporter.py`，OHYA 用 thin shim 引用。

### API 草圖

```python
from closed_loop_kernel.event_reporter import EventReporter

reporter = EventReporter(
    kanban_db_path="/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/ohya/kanban.db",
    kernel_url="postgresql:///ohya_kernel",
    tenant_default="ohya",  # 若 task.tenant 為 NULL 用這個
)
result = reporter.sync()
# result = {"events_imported": 7, "attempts_imported": 3, "failures_opened": 1, "last_event_id": 42}
```

### 主要職責

1. **建立 kernel store 連線** — 用 KernelStore（已驗證會處理 commit / 不洩漏 idle TX）
2. **唯讀打開 kanban.db** — 用 `?mode=ro` URI 防誤寫
3. **讀 checkpoint** — 從 `events` 表找 `event_type='kanban_sync_checkpoint'` 最新一筆
4. **掃 task_events** — `WHERE id > checkpoint.last_event_id ORDER BY id ASC`
5. **掃 task_runs** — `WHERE ended_at IS NOT NULL AND ended_at > checkpoint.last_sync_at`（已完成的 run）
6. **批次寫入 ohya_kernel** — 每批 100 筆走 transaction、失敗整批 rollback
7. **更新 checkpoint** — 成功後寫新一筆 `kanban_sync_checkpoint`

### 容錯設計

- kanban.db 整個讀不到（檔案不存在 / lock / 損毀 嚴重）→ EventReporter raise `KanbanUnavailable`，呼叫端決定要不要重試
- 單筆 row 解析失敗 → log warning、跳過、繼續下一筆
- ohya_kernel 寫入失敗 → 整批 rollback、不更新 checkpoint（下次重試）
- 重複 sync → 用 `task_events.id` 在 ohya_kernel `events.payload.kanban_event_id` 去重

---

## 階段 4 - 6 概要（後續 commits）

- **階段 4**：第一個閉環 demo — 從 OHYA task_runs 抓到 `outcome='crashed'` → 自動 propose `improvement_candidates` → 跑 sandbox replay → 標 `approval_required`
- **階段 5**：Telegram bot 中介 — 偵測 `approval_required` → 推 inline button 訊息 → 收到回應寫回 `approvals` 表
- **階段 6**：1 週觀察期 — 跑真實事件流、看 schema / 對映 / sandbox 還缺什麼

---

## 待 Gary 確認的事項

1. OHYA kanban.db 已知損毀，要不要在 EventReporter 跑起來之前先做一次完整性檢查 + VACUUM / REINDEX？
2. Telegram bot 用哪個 token？OHYA 既有的 coordinator bot 嗎？還是另開一支專門做批准的 bot？
3. EventReporter 跑的頻率？每分鐘？每 5 分鐘？事件驅動（kanban.db 寫入時主動推）？
