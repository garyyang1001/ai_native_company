# Closed Loop Kernel v0 (閉環內核) 主規格書

本文件為 **Closed Loop Kernel v0** 的核心工程規格書。本內核不包含任何「玩具業務展示」，而是專注於建立一個**以 PostgreSQL 作為單一事實來源、歷史不可竄改、自動沙盒重播驗證、且完全受制於人類 DRI 審批安全閘門的自我改進閉環底層系統**。

---

## 1. 核心定義：最底層是什麼？

> [!NOTE]
> **最底層的定義：**
> Closed Loop Kernel v0 的最底層是**一個高安全性的「狀態與變更引擎（State & Change Engine）」**。
> 它藉由**唯增（Append-Only）事件與生命週期日誌**使 AI 具備「對過去的完整可讀性與記憶（Legibility）」，並藉由**隔離雙沙盒（Double Sandbox）與人類審批閘門（Approval Gate）**，使系統在「不竄改歷史事實」與「保障生產安全性」的前提下，實現代碼、Prompt 與資料庫結構的自我修正與遞迴進化。

---

## 2. 逐字稿概念對齊表 (Source Alignment Summary)

| 逐字稿核心概念 | 內核實作與對齊設計 | 偏離玩具 Demo 的工程修正 |
| :--- | :--- | :--- |
| **Sensor Layer & Record Everything** | 透過 `events`、`attempt_lifecycle_events` 與 `attempts` 紀錄捕捉所有輸入/輸出、錯誤訊息，做為 AI 的感官記憶。 | **拒絕 JSONL 作為主記憶**：PostgreSQL 作為 Source of Truth，JSONL 僅作 debug/export 輸出。 |
| **Legibility** | 透過 `artifacts` 對運作 Know-how 進行版本管理，使組織規則對 AI 完全透明。 | **抽象化資料結構**：不設計硬寫的 `employees` 表格，所有追蹤資料完全抽象化。 |
| **Monitoring Query Failures** | 當 Attempt 失敗時建立 `failures` (status='open')。 | **歷史不可改**：原失敗 attempt 的 status 永遠保持 `failed`，保留歷史事實。 |
| **Self-Improvement Loop** | `improvement_candidates` ➔ `replays` (Sandbox 隔離驗證)。 | **雙沙盒安全防禦**：建立 DB DDL Lint 與 SQL 角色隔離沙盒，及 Python AST Subprocess 隔離沙盒，防止 AI 越權修改生產庫。 |
| **Human Supervision** | `approvals` 資料表強制阻斷。 | **審批按鈕阻斷**：沙盒重播失敗時，Approve 按鈕在 UI 上強制 Disabled。 |

---

## 3. PostgreSQL 單一事實來源與唯增歷史防禦

1.  **單一事實來源 (Source of Truth)**：
    所有 attempts、failures、replays、approvals 與 artifacts 的狀態變更均在 PostgreSQL 中以強一致性的交易進行變更。
2.  **歷史不可篡改 (Immutability)**：
    系統中 `events`、`attempt_lifecycle_events`、`attempts`、`tool_calls` 與 `decisions` 為唯讀，在 PostgreSQL 中使用 `BEFORE UPDATE OR DELETE` 觸發器（Trigger）進行實體防禦，防止任何抹滅歷史失敗的行為。
3.  **Attempts 唯增與生命週期分離**：
    歷史的失敗 Attempt 狀態永遠是 `failed`。我們絕不對 `attempts` 執行 UPDATE。系統透過 `attempt_lifecycle_events` 記錄 `'started'` 與 `'running'` 狀態；而在任務結束時以 Batch Trace Transaction 一次性 `INSERT` 最終結果。問題的解決是透過在沙盒中建立 `replays` (status='success')，經 DRI `approval` 後套用變更，並在 Production 重新執行產生新 Attempt (status='success') 來體現。

---

## 4. 系統 Schema 摘要

*   [schema-v0.md](spec/schema-v0.md) 核心表摘要：
    *   `events`：系統內發生的所有泛型事件。
    *   `artifacts`：受版本控制的系統資產（如 Prompt、系統代碼、資料庫 DDL 映射）。
    *   `policy_gates`：系統預設的安全與資源邊界規則。
    *   `attempt_lifecycle_events`：記錄嘗試執行的實時生命週期進度（started, running, finished）。
    *   `attempts`：每次任務執行的嘗試快照（包含輸入與最終輸出/錯誤）。
    *   `decisions`：每個工具呼叫是否被 policy_gate 放行或攔截。
    *   `tool_calls`：一筆 attempt 下細粒度的工具呼叫軌跡。
    *   `failures`：當嘗試失敗時觸發的追蹤紀錄。
    *   `improvement_candidates`：AI 生成的 Prompt/DDL/Code 修正案（包含完整 content_hash、base_artifact_hash、risk_level、rollback_plan 與 validation_assertions 欄位以保證安全部署）。
    *   `replays`：在沙盒環境中對修正案進行的重播驗證紀錄。
    *   `approvals`：人類 DRI 的審批紀錄。

---

## 5. 事件流與 Sandbox/Replay 流程摘要

*   [event-flow-v0.md](spec/event-flow-v0.md) 核心事件鏈：
    1.  **Sensor 階段**：預生成 `attempt_id` ➔ INSERT `attempt_lifecycle_events` (state='started' 及 'running') ➔ 記憶體中收集執行軌跡 ➔ 任務完結時，執行 **Batch Trace Transaction** 一次性 `INSERT` 最終的 `attempts` (status='failed' 或 'success') 與 `tool_calls` / `decisions`。
    2.  **Failure 階段**：任務執行失敗 ➔ Batch Transaction 寫入 `attempts` (status='failed') ➔ 建立 `failures` (status='open')。
    3.  **Sandbox Replay 階段**：
        *   **SQL DDL 變更**：進行 Static SQL Lint (阻斷 DROP/TRUNCATE/public.) ➔ 建立臨時 Schema ➔ 連線極小權限 `sandbox_runner` ➔ 執行驗證。
        *   **Python Code 變更**：進行 AST Static Lint (阻斷敏感模組/檔案寫入) ➔ 啟動隔離 Python Subprocess ➔ 執行驗證。
        *   驗證成功符合 `validation_assertions` ➔ 寫入 `replays` (status='success') ➔ 將 candidate 設為 `sandbox_verified`。
    4.  **Approval 階段**：人類 DRI 審查 ➔ 寫入 `approvals`。
    5.  **原子部署階段**：啟動單一部署 Transaction ➔ **強制四層部署驗證**：
        - 驗證一：最新審批記錄 `decision = 'approved'`。
        - 驗證二：Candidate `status = 'sandbox_verified'`。
        - 驗證三：重播 `replays.status = 'success'`。
        - 驗證四：目標 Artifacts 的當前 `content_hash` 等於 Candidate 的 `base_artifact_hash` (若不符，即發生並發 race condition，自動 ROLLBACK 退回 draft)。
        - 驗證通過 ➔ 新增 active artifacts、使舊 artifacts 失效、更新 candidate 為 `applied`、failure 為 `resolved`。
    6.  **Production Replay 階段**：在 Production 重新執行原任務 ➔ 一次性 `INSERT` 新 `attempts` (status='success')。

---

## 6. 最小 HTML 審批檢視畫面 (UI)

*   [html-views-v0.md](spec/html-views-v0.md) 包含以下 4 個極簡視窗：
    1.  `/events`：事件清單。
    2.  `/events/:id`：垂直 Timeline 視窗（直觀串聯失敗 attempt 到 Sandbox 成功 replay 與人類審批的完整生命軌跡）。
    3.  `/improvements`：AI 生成補丁列表。
    4.  `/approvals`：待審批項目。**Approve 按鈕嚴格受阻斷限制：只有當 Candidate 狀態為 `sandbox_verified` 時才可點擊**；若為 `applied` 或 `rejected` 則永久 Disabled。

---

## 7. 驗證情境定位 (Scenarios)

本內核提供兩個極具代表性、生產級且業務中立的自癒驗證情境，以證實系統的泛用性：
1.  **Scenario 1 (SQL Self-healing)**：[sql-self-healing-v0.md](scenarios/sql-self-healing-v0.md)。以 `public.documents` 查詢失敗為引，AI 自動修正錯誤查詢的 Prompt 範本 Artifact。
2.  **Scenario 2 (Agent Skill Patching)**：[agent-skill-patch-v0.md](scenarios/agent-skill-patch-v0.md)。非 SQL 類型的代碼修補情境，AI Supervisor 發現 Python 技能模組例外，自動生成 AST 級 Code 補丁，在 Python 子進程沙盒重播通過後，部署生效。

---

## 8. v0 驗收標準 (Acceptance Criteria)

完整的驗收標準已載明於 [acceptance-criteria-v0.md](spec/acceptance-criteria-v0.md)。其涵蓋資料庫唯增防篡改、生命週期 Batch Transaction 寫入、靜態與動態雙沙盒安全防線、四層部署校驗阻斷、Production 原子交易套用與孤兒對賬機制等 6 項原型驗收指標。
