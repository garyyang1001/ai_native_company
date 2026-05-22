# Engineering Research Findings (Loop 3 - Fixed)

本文件匯總了針對 **Closed Loop Kernel v0** 五大核心安全與資料流設計的外部深度工程研究。為保障設計的真實性、工程嚴密性與技術深度，所有文獻與實踐均取自具體且權威的 PostgreSQL 官方規格、分散式架構文件、工程部落格與安全 wiki，拒絕任何模糊或首頁級的空泛連結。

---

## 1. 外部工程研究文獻與來源

### A. PostgreSQL 唯增（Append-Only）與防篡改觸發器實作
*   **具體文獻 URL**：[How to make a table read-only or append-only in PostgreSQL - StackOverflow](https://stackoverflow.com/questions/4094599/how-to-make-a-table-read-only-or-append-only-in-postgresql)
*   **取用日期**：2026-05-22
*   **摘要**：在 PostgreSQL 中實作唯增（Append-only）的最安全策略是將權限控制與 `BEFORE UPDATE OR DELETE` 的資料庫觸發器（Trigger）結合，在觸發器內部調用 `RAISE EXCEPTION`。這能硬性阻斷包括 Owner 在內的所有變更意圖。
*   **對本專案的啟發**：
    我們實施 `BEFORE UPDATE OR DELETE` 觸發器鎖死 `attempts` 與 `tool_calls`。這解決了舊設計中「宣告 attempts 唯讀卻在 event-flow 中 UPDATE running -> success/failed」的致命逻辑矛盾。我們將生命週期與最終結果分離，進度實時寫入唯增的 `attempt_lifecycle_events`，而 `attempts` 則在任務完結時，伴隨 `tool_calls` 與 `decisions` 以 Batch Trace Transaction 的形式**單次 INSERT 最終狀態**，徹底消除狀態更新與唯增防護的衝突。

### B. Durable Execution 與基於歷史日誌的 Replay 狀態重建
*   **具體文獻 URL**：[Temporal Concepts: Workflow Execution - Replay - Temporal.io Docs](https://docs.temporal.io/concepts/what-is-a-workflow-execution#replay)
*   **取用日期**：2026-05-22
*   **摘要**： Temporal 等 Durable Execution 框架將執行拆分為「唯增事件歷史日誌（Event History）」與「記憶體狀態」。在暫停或重啟時，系統讀取 append-only 日誌重新執行 Workflow 程式碼，對比已記錄的 Events 進度以跳過執行並還原狀態，這完全依賴於決定性（Deterministic）流程與不可變的歷史。
*   **對本專案的啟發**：
    這印證了我們「一次性寫入 Batch Trace Transaction」與「生命週期事件分離」的架構優勢。核心引擎不需要在過程中頻繁 UPDATE attempts，而是在記憶體 Buffer 中收集 `tool_calls` 與 `decisions`，最終以一個短暫連線的 Transaction 原子性 `INSERT` 到資料庫，保證高度一致的歷史審計，且不會阻礙監控 UI 透過 `attempt_lifecycle_events` 獲取實時狀態。

### C. PostgreSQL SECURITY DEFINER 與 search_path 漏洞及沙盒防禦
*   **具體文獻 URL**：[PostgreSQL 16 Documentation: CREATE FUNCTION - SECURITY DEFINER - PostgreSQL.org](https://www.postgresql.org/docs/current/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)
*   **取用日期**：2026-05-22
*   **摘要**：利用 `CREATE SCHEMA` 搭配變更 `search_path` 進行沙盒隔離時，若未明確限定函數內部的路徑，呼叫者可隨意篡改其 session 的 `search_path` 指向其控制的臨時 schema，並注入同名的惡意函數或物件，實現特權提升（Privilege Escalation）。
*   **對本專案的啟發**：
    這證明了資料庫沙盒隔離絕不能僅依賴 `search_path`。我們的 SQL DDL 沙盒實施三重防線：(1) **Static SQL DDL Linting** 前置防線：在重播前對 DDL 進行語意分析，直接阻斷含有 `DROP TABLE`（臨時沙盒 DDL 除外）、`TRUNCATE`、或帶有任何 `public.` 前綴的語句。(2) 使用獨立的低特權 Role `sandbox_runner` 連線，並執行 `REVOKE ALL ON SCHEMA public FROM PUBLIC` 與 `REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sandbox_runner`。(3) 強制使用完全限定名稱（Fully Qualified Names）存取臨時 Schema 物件。

### D. Python 子進程隔離與 AST 沙盒安全性限制
*   **具體文獻 URL**：[Python Wiki: SandboxedPython - Wiki.python.org](https://wiki.python.org/moin/SandboxedPython)
*   **取用日期**：2026-05-22
*   **摘要**：在同一個 Python Interpreter 進程下，試圖使用 AST 語法過濾來限制 code 行為是俗稱的「玻璃沙盒」（Glass Sandbox），極易被 Python 的動態自省特性（Introspection，如 `().__class__.__base__.__subclasses__()` 等）繞過。要保證執行安全性，必須將安全邊界移到解釋器外部，即使用作業系統級別的隔離子進程與獨立暫存虛擬目錄。
*   **對本專案的啟發**：
    這直接指引了我們**「雙沙盒分離」**的設計。對於 Python Agent Skill 或 Helper 的修補，前置防線會透過 `ast` 模組進行靜態過濾（AST Static Linting），嚴格阻斷調用 `os`、`sys`、`subprocess`、`socket` 等敏感模組；而實際執行 Replay 則必須在獨立的 OS 子進程（Subprocess）中進行，工作目錄完全限制在暫時性虛擬目錄下，且對外部檔案的寫入實施 Mock 重導向，徹底杜絕越權修改生產環境代碼的行為。

### E. PostgreSQL 並發控制與混合鎖定防護
*   **具體文獻 URL**：[Optimistic vs Pessimistic Locking in PostgreSQL - Neon.tech Blog](https://neon.tech/blog/optimistic-vs-pessimistic-locking-in-postgresql)
*   **取用日期**：2026-05-22
*   **摘要**：應用程式在處理高並行數據更新時，若採用 Read-Modify-Write 模式極易發生 Race Condition。為此，結合 `SELECT ... FOR UPDATE` 獲取行級排他鎖（Pessimistic Lock）以及比對版本號/Hash（Optimistic Lock），是防止平行交易相互覆蓋或並行衝突的實際生產實踐。
*   **對本專案的啟發**：
    這項工程實踐直接應用於我們的「四層部署指紋防線」。當人類 DRI 在 UI 上點擊部署經審批通過的 Candidate 時，部署交易啟動：(1) 首先執行 `SELECT content_hash FROM artifacts WHERE name = :name AND is_active = TRUE FOR UPDATE`，以悲觀鎖定目標 Artifact，防止部署期間其他 Agent 修改它。(2) 樂觀校驗指紋：比對該 active hash 是否與 candidate 記錄的 `base_artifact_hash` 一致。如果不一致（說明在 Gary 審批期間該 Prompt 或 Code 已被並行修改），交易立刻 `ROLLBACK`，避免變更覆蓋衝突，將 candidate 退回 draft 狀態。

---

## 2. 核心架構採用決策 (Architectural Decisions)

### 決定採用 (Adopt)
1.  **Attempts 唯增且生命週期分離**：徹底修正致命矛盾。`attempts` 絕不 UPDATE，只在任務完結時一次性 `INSERT`。過程中狀態透過唯增表 `attempt_lifecycle_events` (started, running, finished) 進行實時記錄。
2.  **雙沙盒防禦與 AST Linting**：SQL 沙盒與 Python Code 沙盒徹底分離。引入 Static SQL DDL Linting 與 Python AST Static Linting 做前置過濾，執行端分別使用 `sandbox_runner` 限制角色及作業系統級 subprocess 隔離。
3.  **四層部署指紋防線**：套用變更交易中，強制比對 `latest approved` + `candidate sandbox_verified` + `replay success` + `artifact hash 未變`（使用 `SELECT ... FOR UPDATE` 悲觀行鎖與 `base_artifact_hash` 樂觀指紋比對），一旦不符即自動 `ROLLBACK`。
4.  **精細化 Candidate 欄位**：在 `improvement_candidates` 表中加入 `target_artifact_version`、`base_artifact_hash`、`content_hash`、`rollback_plan` 與 `validation_assertions` 等高維度欄位，確保版本防線與原子復原。
