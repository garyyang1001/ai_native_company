# Next Actions Tracking

本檔案追蹤 **Closed Loop Kernel v0** 收斂後，進入具體編碼與實作階段的具體下一步行動，聚焦可落地的實作步驟。

---

## 1. 具體下一步行動 (Next Actions)

*   **下一個要修的文件**：目前無 Blocker/High 必修文件；本地 interactive prototype 已開始，行為測試、demo、PostgreSQL DDL renderer、Python subprocess sandbox、HTTP UI、approve/reject action 已通過第一批測試。後續文件更新應聚焦 prototype 實作差距，而不是重寫架構。
*   **下一個要驗證的矛盾/工程挑戰**：
    *   ~~建立 `sandbox_runner` 低特權 PostgreSQL role 與動態 Schema (`sandbox_temp_xxxx`)，驗證並發線程下能否穩定建立、切換、清理。~~ **(已完成 2026-05-24)** `closed_loop_kernel/sql_sandbox.py` 內 `SqlSandbox.ensure_role` / `temp_schema` / `run_as_runner` 三 API；6 thread 並發測試已驗證 schema 名稱互不碰撞、所有 schema 在 finally 區塊 CASCADE 清乾淨；安全邊界測試覆蓋「sandbox_runner 不能寫 public schema」與「不能讀 public.attempts」。Spec 偏離：Prototype 走 `SET LOCAL ROLE` 而非獨立物理連線；產線階段需升級。
    *   ~~將 Python subprocess sandbox 加上更明確的資源限制、檔案 policy 與 timeout 行為驗證。~~ **(已完成 2026-05-24)** POSIX `resource` rlimit（CPU/AS/DATA/FSIZE/NPROC/CORE）+ `setsid` process group + `python -I` isolated mode + 最小化環境變數 + wall-clock timeout 後備；測試覆蓋 CPU 超時、環境變數隔離（含 eval+__import__ 繞道路徑），記憶體上限測試於 Linux 平台跑（macOS skip）。下一階段 OS-level sandbox（macOS `sandbox-exec` / Linux seccomp）暫緩。
    *   ~~SQL static lint 黑名單擴充：阻擋角色逃逸（`SET/RESET ROLE`、`SESSION AUTHORIZATION`、`SECURITY DEFINER`）、權限管理（`CREATE/ALTER/DROP ROLE|USER|GROUP`、`GRANT`、`REVOKE`）、broad destruction（`DROP SCHEMA|DATABASE`、`ALTER SYSTEM`）、宿主 I/O（statement-leading `COPY`、`pg_read_file`/`pg_ls_dir`/`lo_*`）。~~ **(已完成 2026-05-24)**
    *   `KernelEngine` 尚未串接 `SqlSandbox`（只有 `replay_code_candidate`，沒有 `replay_sql_candidate`）。下一步加上 SQL 候選 replay API，並把 `scenarios/sql-self-healing-v0.md` 轉成可重跑的 scenario script。
    *   demo/http_app 目前每次啟動都會 `DROP SCHEMA public CASCADE`；後續要設計可重啟保留狀態的 demo 流程（例如分離 seed-once 與 serve 兩個 entry point）。
*   **是否需要 Gary 決策**：**原型代碼編寫不需再進行架構面重大決策。但只要涉及生產環境資料庫異動、真實代碼檔案部署、launchd 系統服務配置、或外部通訊/通知發送（如 Slack/Email 等），仍必須經過 Gary 明確審批授權（Explicit Approval）後方可執行。**
*   **是否可以進入實作**：已進入本地 prototype 實作，PostgreSQL store、Python sandbox hardening 與 SQL sandbox runner 均已落地；下一步是把 `SqlSandbox` 串入 `KernelEngine` 並重跑 Scenario 1（SQL self-healing）。

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
3.  **Phase 3: Real Sandbox Execution**
    *   Python subprocess sandbox 已套用 POSIX rlimit（CPU/AS/DATA/FSIZE/NPROC/CORE）、`setsid` process group、`python -I` isolated mode、最小化 env 與 wall-clock timeout（2026-05-24 完成）；OS-level sandbox（macOS `sandbox-exec` / Linux seccomp）暫緩。
    *   SQL DDL sandbox（`SqlSandbox`）已落地：低權限 `sandbox_runner` role + 動態 `sandbox_temp_<uuid>` schema + `SET LOCAL ROLE` 隔離 + finally CASCADE 清理；並發 6 thread 測試通過；SQL static lint 擴充為角色逃逸 / 權限管理 / broad destruction / 宿主 I/O 完整黑名單（2026-05-24 完成）。下一步把 `SqlSandbox` 串入 `KernelEngine.replay_sql_candidate`。
4.  **Phase 4: Gary Gate UI (interactive action 已開始)**
    *   目前已有 HTTP routes 與本地 approve/reject action；下一步補持久化 DB 與更完整的審核後狀態頁。
5.  **Phase 5: Scenario Runs**
    *   將 `scenarios/sql-self-healing-v0.md` 與 `scenarios/agent-skill-patch-v0.md` 轉成可重跑的 scenario scripts。
