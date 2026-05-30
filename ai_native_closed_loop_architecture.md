# Closed Loop Kernel v0 (閉環內核) 系統架構主入口文件

本文件為 **Closed Loop Kernel v0** 的核心架構設計與主入口文件。本內核拒絕所有玩具級別的展示（如員工資料表查詢），建立一個**以 PostgreSQL 作為單一事實來源、歷史不可變、唯增生命週期監控、自動沙盒重播、且具備四層部署指紋防線與人類審批閘門（Approval Gate）的 AI 自我改進閉環底層系統架構**。

---

## 1. 核心大腦架構與最底層定義
Closed Loop Kernel v0 的最底層是**一個高安全性的「狀態與變更引擎（State & Change Engine）」**。它藉由**唯增（Append-Only）事件與生命週期日誌**使 AI 具備「對過去的完整可讀性與記憶（Legibility）」，並藉由**隔離雙沙盒（PostgreSQL DDL Lint/Role 沙盒與 Python AST 子進程沙盒）與人類審批閘門（Approval Gate）**，使系統在「不竄改歷史事實」與「保障生產安全性」的前提下，實現代碼、Prompt 與資料庫結構的自我修正與遞迴進化。

---

## 2. 規格書與研究報告目錄 (Table of Contents)

為了落實嚴謹的工程開發，我們將內核的各個模組拆分為獨立的規格書與研究報告，儲存於工作區中：

### 🛠️ 核心規格 (Specifications)
1.  **[Closed Loop Kernel v0 主規格書 (closed-loop-kernel-v0.md)](spec/closed-loop-kernel-v0.md)**：內核的核心定義、逐字稿概念對齊、PostgreSQL 唯增歷史原則與核心事件鏈摘要。
2.  **[PostgreSQL 資料表設計 (schema-v0.md)](spec/schema-v0.md)**：包含抽象實體（`events`, `attempt_lifecycle_events`, `attempts`, `tool_calls`, `decisions`, `failures`, `candidates`, `replays`, `approvals`, `artifacts`）的 DDL 定義，以及防篡改 Trigger 實作。
3.  **[內核事件流 (event-flow-v0.md)](spec/event-flow-v0.md)**：定義任務從輸入預生成 ID ➔ 生命週期唯增寫入 ➔ 任務完結 Batch Trace Transaction ➔ 雙沙盒隔離驗證 ➔ 審批通過 ➔ 四層部署驗證（防 Race Condition 競合）➔ 原子套用的完整事件序列。
4.  **[極簡 HTML 審批檢視 (html-views-v0.md)](spec/html-views-v0.md)**：定義 `/events`、`/events/:id`、`/improvements` 與 `/approvals` 四個畫面的欄位、按鈕狀態與審批阻斷邏輯。
5.  **[內核驗收標準 (acceptance-criteria-v0.md)](spec/acceptance-criteria-v0.md)**：包含資料庫唯讀防篡改、不吞錯單次批次寫入、雙沙盒安全防線、四層部署指紋校驗、原子回滾與孤兒對賬機制等 6 項原型驗收指標與測試斷言。

### 🧪 驗證情境 (Scenarios)
1.  **[SQL Self-Healing 驗證情境 (sql-self-healing-v0.md)](scenarios/sql-self-healing-v0.md)**：使用中性 Domain 的「企業文件庫 (`documents`)」做為驗證內核閉環（Failure ➔ SQL Sandbox Replay ➔ DRI Approval ➔ Four-tier Deploy ➔ Retry Success）的第一驗證場景。
2.  **[Agent Skill Code Patching 驗證情境 (agent-skill-patch-v0.md)](scenarios/agent-skill-patch-v0.md)**：驗證非 SQL 類型的自癒能力。展示 Python 輔助函數計算拋出例外時，內核如何進行 AST 靜態語法樹 Linting、Subprocess 隔離沙盒重播，並於人類審批通過後原子升級代碼資產。

### 📝 研究與自檢紀錄 (Notes)
1.  **[逐字稿對齊與 Toy Demo 修正分析 (source-alignment.md)](notes/source-alignment.md)**：深度對齊 YC 夥伴逐字稿，分析與修正過往玩具 Demo 陷阱。
2.  **[外部工程研究報告 (research-findings.md)](notes/research-findings.md)**：匯總並分析 PostgreSQL 防篡改觸發器、Durable Workflow 生命週期日誌、SECURITY DEFINER 漏洞、Python 玻璃沙盒 AST 陷阱，以及並發 Optimistic/Pessimistic Locking 混合鎖部署等 5 個真實、具體的外部技術來源。
3.  **[自我檢查與殘留風險報告 (self-review.md)](notes/self-review.md)**：以務實客觀態度列出兩輪自檢修復清單，冷靜探討「沙盒資料依賴」、「審批並行死鎖」、「自動斷言幻覺」等三個殘留風險與緩解策略。

### 🧭 部門應用層模組 (Department Application Modules)
1.  **[AI Native SEO Module v0](docs/ai-native-seo-module-v0.md)**：第一個正式部門應用層模組，定義官網、GSC、GA4、社群海巡、回文建議、審核與 Hermes OHYA 乾淨接法。

---

## 3. 開工準備與下一步行動 (Action Plan)

本內核規格已完成多輪嚴謹的自我審查與修正，設計結構非常清晰，工程開工細節已經齊全。

### 下一步開工指令 (For Next Run)：
1.  **資料庫初始化**：在 PostgreSQL 中執行 [schema-v0.md](spec/schema-v0.md) 定義的 DDL 建表與 `prevent_mutation` 防篡改觸發器安裝。
2.  **內核代碼編寫**：以 [event-flow-v0.md](spec/event-flow-v0.md) 為邏輯基礎，編寫實體程式碼。
3.  **雙沙盒防禦開發**：實施靜態 SQL 語法 Lint 與 Python AST 語法過濾，以及 `sandbox_runner` 低特權連線與隔離 Subprocess 調用。
4.  **驗收測試**：執行 [acceptance-criteria-v0.md](spec/acceptance-criteria-v0.md) 中定義的 6 項原型驗收指標測試斷言。
