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
    *   demo/http_app 目前每次啟動都會 `DROP SCHEMA public CASCADE`；後續要設計可重啟保留狀態的 demo 流程（例如分離 seed-once 與 serve 兩個 entry point），讓 Gary 能多次開瀏覽器看歷史不被重置。
    *   `views.py` / `http_app.py` 目前只認得 `code_patch`；要把 `sql_patch` 在 `/improvements` 與 `/approvals` 頁面以可讀方式呈現（含 sandbox_schema、replay rows 摘要）。
    *   產線階段升級：把 SqlSandbox 從 `SET LOCAL ROLE` 改成獨立 `psycopg.connect(user=sandbox_runner)` 物理連線（需設定 trust auth 或 password）。
*   **是否需要 Gary 決策**：**原型代碼編寫不需再進行架構面重大決策。但只要涉及生產環境資料庫異動、真實代碼檔案部署、launchd 系統服務配置、或外部通訊/通知發送（如 Slack/Email 等），仍必須經過 Gary 明確審批授權（Explicit Approval）後方可執行。**
*   **是否可以進入實作**：已進入本地 prototype 實作，Phase 1-3 與 Scenario 1/2 端到端 demo 均已落地；下一步聚焦 demo/http_app 可重啟、UI 加上 `sql_patch` 顯示路徑，與 production-grade sandbox_runner 物理連線升級（後者需 Gary 在配 trust auth / password 時參與）。

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
4.  **Phase 4: Gary Gate UI (interactive action 已開始)**
    *   目前已有 HTTP routes 與本地 approve/reject action；下一步補：(a) demo/http_app 啟動分離 seed-once 與 serve，避免每次 `DROP SCHEMA public`；(b) `views.py` / `http_app.py` 加上 `sql_patch` 顯示路徑（含 sandbox_schema、replay rows 摘要）。
5.  **Phase 5: Scenario Runs (已完成 2026-05-24)**
    *   `closed_loop_kernel/demo.py` 跑 Scenario 2（Python 技能 patch）端到端閉環。
    *   `closed_loop_kernel/sql_demo.py` 跑 Scenario 1（SQL self-healing）端到端閉環。
