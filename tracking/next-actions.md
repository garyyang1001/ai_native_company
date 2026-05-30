# Next Actions Tracking

本檔案追蹤 **Closed Loop Kernel v0** 收斂後，進入具體編碼與實作階段的具體下一步行動，聚焦可落地的實作步驟。

---

## 1. 具體下一步行動 (Next Actions)

*   **下一個要修的文件**：目前無 Blocker/High 必修文件；本地 interactive prototype 已開始，行為測試、demo、PostgreSQL DDL renderer、Python subprocess sandbox、HTTP UI、approve/reject action 已通過第一批測試。後續文件更新應聚焦 prototype 實作差距，而不是重寫架構。
*   **下一個要驗證的矛盾/工程挑戰**：
    *   ~~建立 `sandbox_runner` 低特權 PostgreSQL role 與動態 Schema (`sandbox_temp_xxxx`)。~~ **(已完成 2026-05-24)**
    *   ~~將 Python subprocess sandbox 加上資源限制 / 檔案 policy / timeout 驗證。~~ **(已完成 2026-05-24)**
    *   ~~SQL static lint 黑名單擴充。~~ **(已完成 2026-05-24)**
    *   ~~`KernelEngine.replay_sql_candidate` 串接 SqlSandbox，並把 Scenario 1 轉成可重跑 script。~~ **(已完成 2026-05-24)** `closed_loop_kernel/engine.py` 新增 `replay_sql_candidate`；`closed_loop_kernel/sql_demo.py` 跑完整閉環（fail → propose → sandbox replay → approve → apply → retry success）並有對應測試。
    *   ~~demo/http_app 目前每次啟動都會 `DROP SCHEMA public CASCADE`；後續要設計可重啟保留狀態的 demo 流程。~~ **(已完成 2026-05-24)** `http_app` 拆成 `serve`（預設、不 reset）/ `seed` / `seed-and-serve` 三個 subcommand；新增 `open_store()` 與 `seed_demo_store()`；順手修了 `KernelStore` 讀方法不 commit 造成連線停在 "idle in transaction" 的 pre-existing bug。
    *   ~~`views.py` / `http_app.py` 目前只認得 `code_patch`；要把 `sql_patch` 在 `/improvements` 與 `/approvals` 頁面以可讀方式呈現（含 sandbox_schema、replay rows 摘要）。~~ **(已完成 2026-05-24)** `_patch_label` 加 `sql_patch → "SQL 修正"`；`/improvements` 表格新增「沙盒 schema」欄；`/approvals` 卡片顯示 patch_type 標籤、隔離 schema、replay row count 與第一筆樣本 JSON。
    *   **OHYA production slice 只接 `cms-draft-executor`**：第一輪只接 OHYA 的單一 profile，`EventReporter(profile_filter="cms-draft-executor")` 會把其他 profile、壞 JSON、缺欄位、未完成 run、不支援 outcome 全部放進 `skipped_rows`，避免髒資料污染 kernel。
    *   產線階段升級：把 SqlSandbox 從 `SET LOCAL ROLE` 改成獨立 `psycopg.connect(user=sandbox_runner)` 物理連線（需設定 trust auth 或 password）。
*   **是否需要 Gary 決策**：**原型代碼編寫不需再進行架構面重大決策。但只要涉及生產環境資料庫異動、真實代碼檔案部署、launchd 系統服務配置、或外部通訊/通知發送（如 Slack/Email 等），仍必須經過 Gary 明確審批授權（Explicit Approval）後方可執行。**
*   **是否可以進入實作**：已進入本地 prototype 實作，Phase 1-5 與 OHYA `cms-draft-executor` profile slice 均已落地在程式層；下一步聚焦用隔離 snapshot 跑 OHYA slice，而不是直接寫 live kanban.db。

---

## 1.1 下一個可自主開發目標

**目標名稱**：OHYA `cms-draft-executor` isolated snapshot runner

**白話目的**：不要直接動 OHYA live runtime。先複製一份 OHYA `kanban.db` 到隔離位置，讓 Gary kernel 在安全快照上跑一次 `cms-draft-executor` 切片，產出 Gary 看得懂的報告。

**可以自主開發的範圍**：

1. 新增一個本地 runner，例如 `closed_loop_kernel/ohya_snapshot_runner.py`。
2. runner 接受 `--source-kanban-db`、`--kernel-url`、`--output-dir`、`--profile-filter` 等參數。
3. runner 先把來源 DB 複製到隔離暫存位置，再用唯讀模式交給 `EventReporter`。
4. runner 輸出 JSON 報告與繁中 Markdown 報告，內容至少包含 imported events、imported attempts、opened failures、skipped_by_reason、skipped_rows 摘要、是否產生 candidate。
5. 加測試確認：不寫回來源 DB、profile filter 生效、dirty rows 統計會進報告、缺 `KERNEL_DATABASE_URL` 時有清楚錯誤。

**禁止事項**：

1. 不讀 credentials。
2. 不發 Telegram、Slack、Email 或任何外部通知。
3. 不設定 launchd / cron / background service。
4. 不修改 OHYA live `kanban.db`、HermesRuntime state 或 production DB。
5. 不把 snapshot 報告當作 production migration 結果。

**完成標準**：

1. `python3 -m unittest discover -s tests` 通過或明確列出因環境缺少 PostgreSQL 而 skipped 的測試。
2. `git diff --check` 通過。
3. 報告格式中每個技術欄位旁邊都有白話解釋。
4. `rg` 確認本 repo 受管開發文件沒有回到外部客戶 proof target 敘述。

---

## 2. 工程編碼實作步驟指引 (Implementation Sequence)

目前第一批本地 prototype 已落地，接續工作依以下順序：

1.  **Phase 1: Local Prototype Baseline (已完成)**
    *   `closed_loop_kernel/store.py` 建立 PostgreSQL schema、`prevent_mutation` append-only trigger 與本地查詢 helper（`psycopg` + `KERNEL_DATABASE_URL`）。
    *   `closed_loop_kernel/engine.py` 實作 attempt lifecycle、failure、candidate、replay、approval、apply、orphan reconciliation。
    *   `tests/` 覆蓋 append-only、四層 apply gate、hash mismatch、orphan reconciliation、SQL/Python lint，並包含 PostgreSQL-backed integration suite (`test_postgres_store.py`)。
2.  **Phase 2: PostgreSQL Integration (已完成)**
    *   PostgreSQL DDL 與 `prevent_mutation` trigger 已成為實際 runtime，不再是 renderer-only。
    *   PostgreSQL integration test 已驗證外鍵、trigger、transaction rollback 行為一致。
3.  **Phase 3: Real Sandbox Execution (已完成 2026-05-24)**
    *   Python subprocess sandbox：POSIX rlimit（CPU/AS/DATA/FSIZE/NPROC/CORE）+ `setsid` process group + `python -I` isolated mode + 最小化 env + wall-clock timeout。OS-level sandbox（macOS `sandbox-exec` / Linux seccomp）暫緩。
    *   SQL DDL sandbox：低權限 `sandbox_runner` role + 動態 `sandbox_temp_<uuid>` schema + `SET LOCAL ROLE` 隔離 + finally CASCADE 清理；並發 6 thread 測試通過；SQL static lint 擴充為完整 escape 黑名單；`KernelEngine.replay_sql_candidate` 已串入。
4.  **Phase 4: Gary Gate UI (已完成 2026-05-24)**
    *   HTTP routes、本地 approve/reject action 已落地。
    *   `http_app` serve/seed/seed-and-serve subcommand 拆分，預設 serve 不 reset、保留歷史。
    *   `/improvements` 與 `/approvals` 兩個頁面已支援 `sql_patch` 候選：表格加「沙盒 schema」欄，卡片顯示 patch_type 標籤 + 隔離 schema + replay row count 與第一筆樣本。
5.  **Phase 5: Scenario Runs (已完成 2026-05-24)**
    *   `closed_loop_kernel/demo.py` 跑 Scenario 2（Python 技能 patch）端到端閉環。
    *   `closed_loop_kernel/sql_demo.py` 跑 Scenario 1（SQL self-healing）端到端閉環。
