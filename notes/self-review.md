# Self-Review & Remaining Risks Report (Loop 3 - Fixed)

本文件紀錄 **Closed Loop Kernel v0** 的自我審查報告。我們已剔除所有誇大與過度自信的詞彙（如「完美」、「工業級」），改以務實、冷靜的工程態度，對內核設計進行審查，並列出當前的**殘留風險 (Remaining Risks)** 與相應的緩解措施。

---

## 1. 第一輪自我審查 (Round 1 Review)
*   **重點**：解決 `attempts` 狀態更新與防篡改的邏輯矛盾、Schema 完整性。

### 核心修正與對齊

*   **修正 attempts UPDATE 矛盾**：
    *   *發現問題*：舊規格同時宣告了 `attempts` table 唯讀（防篡改觸發器）與 `event-flow` 中「更新 attempt running ➔ success/failed」的行為，這在資料庫層面會直接導致 DDL 觸發器報錯。
    *   *修復方案*：徹底改變執行流。`attempts` 資料表改為 **Only-Once INSERT（單次寫入，永不更新）**。
        1. 引入 `attempt_lifecycle_events` 表，當任務開始與執行時，向此唯增表寫入狀態進度（started, running）日誌。
        2. 任務執行期間，所有的詳細工具呼叫與決策記錄在 `tool_calls` 與 `decisions` 表中，完全不在 attempts 中寫入中間狀態。
        3. 當任務最終完成（成功或失敗）時，核心引擎才開啟一個原子交易，向 `attempts` 寫入最終的一筆 outcome 資料（status 為 `success` 或 `failed`），並寫入 finished 到 lifecycle 表。
        4. 如此一來，`attempts` 僅有單次 INSERT，符合唯增（Append-Only）與防篡改觸發器的要求。
*   **補完 v0 核心資料表**：
    *   補齊了 `tool_calls` (工具呼叫軌跡)、`decisions` (決策日誌)、`policy_gates` (行為邊界規則) 三張核心表，使內核具備細粒度審計與安全規則攔截能力。
*   **修正 UUID 套件**：
    *   移除錯誤的 `uuid-ossp`，改用 PostgreSQL 原生的 `pgcrypto` 支援 `gen_random_uuid()`，避免依賴外部非原生套件。

---

## 2. 第二輪自我審查 (Round 2 Review)
*   **重點**：沙盒安全防禦強化、多 Agent 競爭危害（Race Condition）防護。

### 核心安全強化

*   **強化沙盒防禦機制**：
    *   *之前隱憂*：單靠 `search_path` 可能會因為 DDL 中的 `public.` 前綴或惡意 `DROP/TRUNCATE` 被繞過。
    *   *修復方案*：
        1. **Lint 靜態攔截**：AI 生成的 DDL/Code 在進入沙盒前，必須經過 AST Lint。對於 SQL，阻斷含 `DROP`（臨時 sandbox 除外）、`TRUNCATE` 或 `public.` 關鍵字；對於 Python 代碼，解析 AST 阻斷 `os`, `sys`, `subprocess` 等敏感模組。
        2. **極小權限帳號**：SQL Sandbox 執行改用 `sandbox_runner` role，收回 `public` schema 權限。
        3. **分離沙盒**：代碼補丁（Code Patch）在獨立的 Python Subprocess 中執行並 Mock 檔案寫入；資料庫 Schema 在 PostgreSQL Sandbox Schema 中執行，兩者隔離。
*   **防範 Race Condition (部署指紋校驗)**：
    *   *之前隱憂*：當 AI 偵測到 failure ➔ 生成 candidate (基於 version 1 的 Prompt) ➔ 在 Gary 點擊 Approve 期間，另一個 Agent 或人類修改了 Prompt 變成 version 2。如果此時執行部署，將會把基於 version 1 設計的 Patch 覆蓋到 version 2 上，導致 Regression。
    *   *修復方案*：在部署套用交易中，強制比對當前 active 資源的 Hash 是否與 Candidate 生成時所依據的 `base_artifact_hash` 一致（使用 `SELECT ... FOR UPDATE` 悲觀行鎖）。如果不一致，交易立刻 `ROLLBACK`，將 candidate 退回 draft 狀態以重新 Replay。
*   **部署審批四層防線**：
    *   部署前強制核對四層指標：最新一筆為決策通過的 approvals 記錄 (`decision = 'approved'`)、candidate 狀態為 `sandbox_verified`、重播 `replays.status = 'success'`、目標資產 active hash 與 `base_artifact_hash` 一致。

---

## 3. 殘留風險 (Remaining Risks) 與緩解策略

儘管 v0 規格已大幅強化，在實際工程落地與高並發的生產環境中，仍存在以下殘留風險：

### 1. 隔離沙盒中的「資料狀態依賴」風險
*   **風險說明**：當在 `sandbox_temp_xxxx` 重播查詢時，若該查詢依賴特定的資料狀態（例如：查詢「上月金額 > 10000 的訂單」，但沙盒是空資料表），Replay 雖然不會報錯，但會回傳空結果。這可能導致 `validation_assertions` 的斷言（例如結果必須包含特定欄位）失效。
*   **緩解策略**：在後續版本中，引入安全去識別化資料複製工具，在執行 Sandbox Replay 前，將少量的脫敏業務資料複製到 sandbox schema，供 replay 執行。

### 2. 多重 Agent 併發審批競爭與資料庫死鎖
*   **風險說明**：多個不同的失敗事件產生了多個變更 Candidate。如果人類 DRI 快速連續點擊「Approve」部署不同的 DDL 或 Code 變更，可能會在多個 concurrent 交易中發生資料庫死鎖 (Deadlock) 或衝突。
*   **緩解策略**：部署引擎在套用前應執行 `LOCK TABLE artifacts IN EXCLUSIVE MODE` 或者是使用 Advisory Locks，確保部署交易在資料庫層面完全序列化。

### 3. 自動斷言生成 (validation_assertions) 的幻覺與誤判
*   **風險說明**：AI Supervisor 自動生成的 `validation_assertions`（驗證斷言）本身可能包含語意幻覺或過於苛刻，導致本來正確的程式碼或 SQL 修正案被誤判為失敗，進而無法提供給 Gary 審批。
*   **緩解策略**：在 v0 中，限制自動斷言僅使用確定性的系統指標（如 `error_code IS NULL`、`row_count >= 0`）。複雜的語意斷言必須有預設的安全閥值，或允許人類 DRI 在審批畫面上手動修改斷言。
