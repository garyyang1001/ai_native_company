# Source Alignment Analysis (Loop 0)

本文件將當前設計的 **Closed Loop Kernel v0** 與 `X_JsIHUfUjc-transcript.txt` 逐字稿進行深度概念對齊分析，盤點現有架構的對齊程度、過往玩具 Demo（Toy Demo）的陷阱，以及實現實際生產落地所缺少的工程細節。

---

## 1. 逐字稿核心概念對齊表 (Alignment Map)

| 逐字稿核心概念 | 逐字稿原文定位 (Quotes / Context) | Kernel v0 實作與對齊設計 |
| :--- | :--- | :--- |
| **Sensor Layer**<br>(感測層) | *Line 80-87*: "You start with like a sensor layer... emails from your customers. Might be support tickets, code changes... product telemetry." | 對齊於 `events` 資料表。捕捉系統的所有外部觸發（如查詢請求、人工指令、系統排程），做為整個大腦感知真實世界的感測輸入。 |
| **Record Everything**<br>(記錄一切) | *Line 242-255*: "make the entire organization legible... record everything. every single thing that happens, if it is recorded, it happened to the AI." | 對齊於 `attempts` 與 `failures` 表。每一次執行嘗試、工具呼叫、輸入/輸出、錯誤訊息皆寫入 PostgreSQL。**絕非僅記錄於臨時日誌 (JSONL) 或內存**，而是將歷史轉為永久、唯增（Append-only）的結構化記錄。 |
| **Legibility**<br>(組織可讀性) | *Line 63-68*: "domain knowledge... inside the heads of people... If you can make that legible, you suddenly can move..." | 透過 `artifacts` 表對版本化資產（提示詞、資料庫 Schema、操作代碼）進行結構化管理，將企業的運行 Know-how 轉化為 AI 可讀、可比對的結構化資產。 |
| **Monitoring Query Failures**<br>(監控查詢失敗) | *Line 128-135*: "...put a monitoring agent on top of that which looked at every single query... and saw when it worked and when it did not work..." | 對齊於 `failures` 追蹤機制。當 `attempts` 狀態為 `failed` 時，觸發 `attempt_failed` 事件，並於 `failures` 表建立 Open 狀態的失敗追蹤，自動擷取報錯上下文。 |
| **Self-Improvement Loop**<br>(自我遞迴改進) | *Line 146-150*: "...the AI going through this loop to figure out how to self-improve... your company gets better while you are sleeping." | 對齊於 `improvement_candidates` 與 `replays` 機制。Supervisor 偵測到 failure 後，自動分析根因，生成 Patch，並在 Sandbox 中重播驗證，達成閉環修正。 |
| **Tools / Skills / DB View / Index**<br>(工具與技能優化) | *Line 91-96, 136-139*: "A tool layer... Gary's skills and code... why not... do we need different deterministic tools... db view... new index?" | `improvement_candidates` 的 `patch_type` 支持 `prompt_update`（優化 Tools/Skills 提示詞）以及 `db_migration`（自動建立 PostgreSQL Index, View 或 DDL 遷移），精確呼應逐字稿所述。 |
| **Human Supervision / Quality Gate**<br>(品質閘門與人類監管) | *Line 97-100, 152-156*: "...a quality gate... evals, safety filters, human review for high-risk stuff... have the human and kind of a monitoring of supervisory capacity..." | 對齊於 `replays`（自動沙盒 Evals）與 `approvals`（人類審批閘門）。AI **絕無直接修改 Production 的權力**，代碼或結構變更必須通過 Sandbox 重播驗證，並由人類 DRI 審批後方能 Apply。 |

---

## 2. 玩具 Demo（Toy Demo）陷阱盤點

在之前的設計版本中，存在以下滑向「玩具 Demo」的設計陷阱，我們在 Kernel v0 中予以徹底根除：

*   **陷阱一：硬寫的「員工查詢（Employees Table）」資料模型**
    *   *問題*：前幾版將 SQL Healing 綁死在一個玩具級的 `employees` 表格與「誰是 CTO」的查詢。這只是一個臨時展示，無法推廣到任何真實企業場景。
    *   *修正*：Kernel v0 的資料結構與業務資料表完全解耦。資料庫中只儲存抽象的 `event`, `attempt`, `failure`, `candidate`, `replay`。這套模型適用於任何領域的自動修復。
*   **陷阱二：將 JSONL 日誌作為大腦的主記憶體**
    *   *問題*：前版將 `logs.jsonl` 當作 AI 的學習依據，這是在模擬單機玩具。JSONL 容易損毀、無法建立複雜關聯（如 Failure 到 Candidate 到 Replay 的一對多關係）、不支援交易（Transactions）。
    *   *修正*：將 PostgreSQL 作為單一事實來源，JSONL 降級為僅供 Export/Debug 與本機日誌輸出使用。
*   **陷阱三：直接竄改歷史紀錄的成功狀態**
    *   *問題*：前版寫道「修復後將原 logs.jsonl 中的 success 修改為 true」。這在真實系統中是**災難性的審計漏洞**。歷史發生的失敗是真實存在的，不可抹滅。
    *   *修正*：歷史 Attempt 永遠保持 `status = 'failed'`。修復成功是透過新增一個 `replays` (status = 'success') 與後續新的 `attempts` (status = 'success') 來證明。

---

## 3. 系統實作所需之具體工程細節

要讓 Kernel v0 從規劃走向真正可以開工的代碼，我們必須在後續的詳細設計中補足以下關鍵細節：

1.  **PostgreSQL 沙盒隔離機制 (Schema-based Sandboxing)**：
    *   在同一個 Postgres 實例中，如何利用 `CREATE SCHEMA sandbox_xxx` 複製生產結構？
    *   如何設定 `SET search_path = sandbox_xxx` 限制 AI 生成的 DDL 影響到 Production（`public`）？
2.  **自動化斷言驗證 (Assertion-based Replay Testing)**：
    *   Replay 成功不能只看 SQL 有沒有報錯，還必須驗證結果（例如結果筆數、資料欄位是否存在）。如何設計動態斷言？
3.  **變更部署的原子性 (Atomic Patch Application)**：
    *   當人類 DRI 給予 Approval 後，如何確保 DDL 遷移與 Artifacts 版本更新是在同一個資料庫 Transaction 中完成？如果 DDL 失敗，如何自動 Rollback？

這些缺少的細節將在接下來的 `spec/schema-v0.md` 與 `spec/event-flow-v0.md` 中被逐一補足與落實。
