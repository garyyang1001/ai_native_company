# Next Actions Tracking

本檔案追蹤 **Closed Loop Kernel v0** 收斂後，進入具體編碼與實作階段的具體下一步行動，聚焦可落地的實作步驟。

---

## 1. 具體下一步行動 (Next Actions)

*   **下一個要修的文件**：目前無 Blocker/High 必修文件；本地 interactive prototype 已開始，行為測試、demo、PostgreSQL DDL renderer、Python subprocess sandbox、HTTP UI、approve/reject action 已通過第一批測試。後續文件更新應聚焦 prototype 實作差距，而不是重寫架構。
*   **下一個要驗證的矛盾/工程挑戰**：
    *   建立 `sandbox_runner` 低特權 PostgreSQL role 與動態 Schema (`sandbox_temp_xxxx`)，驗證並發線程下能否穩定建立、切換、清理。
    *   將 Python subprocess sandbox 加上更明確的資源限制、檔案 policy 與 timeout 行為驗證。
    *   demo/http_app 目前每次啟動都會 `DROP SCHEMA public CASCADE`；後續要設計可重啟保留狀態的 demo 流程（例如分離 seed-once 與 serve 兩個 entry point）。
*   **是否需要 Gary 決策**：**原型代碼編寫不需再進行架構面重大決策。但只要涉及生產環境資料庫異動、真實代碼檔案部署、launchd 系統服務配置、或外部通訊/通知發送（如 Slack/Email 等），仍必須經過 Gary 明確審批授權（Explicit Approval）後方可執行。**
*   **是否可以進入實作**：已進入本地 prototype 實作，PostgreSQL store 已落地；下一步是 SQL sandbox runner（低特權 role + 動態 schema）與 Python sandbox hardening（資源/檔案/timeout policy）。

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
    *   實作 `sandbox_runner` role、動態 schema 建立、SQL replay。
    *   Python subprocess sandbox 已有第一版；下一步補資源限制、檔案 policy 與 timeout 驗證。
4.  **Phase 4: Gary Gate UI (interactive action 已開始)**
    *   目前已有 HTTP routes 與本地 approve/reject action；下一步補持久化 DB 與更完整的審核後狀態頁。
5.  **Phase 5: Scenario Runs**
    *   將 `scenarios/sql-self-healing-v0.md` 與 `scenarios/agent-skill-patch-v0.md` 轉成可重跑的 scenario scripts。
