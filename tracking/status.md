# System Tracking Status

本檔案記錄 **Closed Loop Kernel v0** 的整體開發與原型驗證狀態。本檔案將隨每次檢查與驗證動態更新，只有在無 Blocker/High 殘留問題，且通過驗證檢查後，狀態方可標為 `ready-for-prototype-build`。

---

## 1. 核心狀態摘要 (Status Summary)

*   **目前整體狀態**：`postgres-prototype-landed` (PostgreSQL-backed KernelStore、Python subprocess sandbox、HTTP UI 與 approve/reject action 第一批測試已通過；非正式生產部署級)
*   **最近一次修改時間**：2026-05-24T00:00:00+08:00
*   **剩餘 Open Issues**：
    *   **Blocker/High**: 0
    *   **Deferred Medium/Low (已知風險)**: 3 (詳見 tracking/open-issues.md)
*   **是否符合 Gary 的硬性要求**：符合原型階段硬性要求；仍有 3 個 deferred Medium/Low 風險

---

## 2. 已完成與受追蹤文件清單 (Tracked Documents)

| 類別 | 檔案名稱 | 說明 | 狀態 |
| :--- | :--- | :--- | :--- |
| **主入口** | [ai_native_closed_loop_architecture.md](ai_native_closed_loop_architecture.md) | 系統整體架構與 TOC 大綱入口 | `Reviewed` |
| **核心規格** | [closed-loop-kernel-v0.md](spec/closed-loop-kernel-v0.md) | 最底層閉環內核規格說明 | `Reviewed` |
| **核心規格** | [schema-v0.md](spec/schema-v0.md) | 11 張核心表抽象 DDL 設計 | `Reviewed` |
| **核心規格** | [event-flow-v0.md](spec/event-flow-v0.md) | 唯增 lifecycle 與部署事件流 | `Reviewed` |
| **核心規格** | [html-views-v0.md](spec/html-views-v0.md) | 4 個極簡 UI 畫面與按鈕安全阻斷 | `Reviewed` |
| **核心規格** | [acceptance-criteria-v0.md](spec/acceptance-criteria-v0.md) | 6 項原型驗收指標與測試 Assertion | `Reviewed` |
| **驗證場景** | [sql-self-healing-v0.md](scenarios/sql-self-healing-v0.md) | Scenario 1: 中性文件庫 DDL Prompt 自癒 | `Reviewed` |
| **驗證場景** | [agent-skill-patch-v0.md](scenarios/agent-skill-patch-v0.md) | Scenario 2: 非 SQL python helper 技能自癒 | `Reviewed` |
| **研究自檢** | [source-alignment.md](notes/source-alignment.md) | YC 逐字稿概念對齊與玩具 Demo 陷阱剖析 | `Reviewed` |
| **研究自檢** | [research-findings.md](notes/research-findings.md) | 5 個真實、具體的外部技術來源與啟發 | `Reviewed` |
| **研究自檢** | [self-review.md](notes/self-review.md) | 務實自檢、剔除自嗨詞、詳列 3 大殘留風險 | `Reviewed` |
| **本地 prototype** | [PROTOTYPE.md](PROTOTYPE.md) | 本地可跑 prototype 範圍、命令與邊界 | `In Progress` |
| **本地 prototype** | [closed_loop_kernel/](closed_loop_kernel/) | PostgreSQL store 與核心 engine 初版 | `In Progress` |
| **本地 prototype** | [closed_loop_kernel/postgres.py](closed_loop_kernel/postgres.py) | PostgreSQL DDL renderer 初版 | `In Progress` |
| **本地 prototype** | [closed_loop_kernel/sandbox.py](closed_loop_kernel/sandbox.py) | Python subprocess sandbox 初版 | `In Progress` |
| **本地 prototype** | [closed_loop_kernel/views.py](closed_loop_kernel/views.py) | 4 個最小 HTML views renderer 初版 | `In Progress` |
| **本地 prototype** | [closed_loop_kernel/http_app.py](closed_loop_kernel/http_app.py) | 本地 HTTP UI server 初版 | `In Progress` |
| **本地 prototype** | [tests/](tests/) | acceptance 行為測試初版 | `Passing` |

---

## 3. Gary 硬性要求核對清單 (Gary's Guardrails)

*   [x] **無 Employees / 員工資料表玩具 Demo**：已改用中性業務 Domain `documents` 與 `tags`。
*   [x] **無 Typeless 誤打前提**：目前受追蹤規格已移除 typeless 設計。
*   [x] **PostgreSQL 作為單一事實來源**：狀態紀錄儲存於 PostgreSQL 實體表中，不以 JSONL 作為主狀態來源。
*   [x] **歷史不可篡改防線**：`attempts` 中此 `attempt_id` 只有一筆 `failed` 記錄，不進行 UPDATE 抹滅失敗事實。
*   [x] **不中途 UPDATE attempts**：中途狀態由唯增表 `attempt_lifecycle_events` 記錄，完結期原子 Batch Trace Transaction 一次性 INSERT。
*   [x] **雙沙盒安全防禦**：SQL DDL 沙盒（Static SQL Lint + least-privilege role 權限收回）與 Python Code 沙盒（AST Lint + Subprocess 隔離虛擬環境）分離設計。
*   [x] **四層部署指紋防禦**：最新 approvals 批准 + candidate `sandbox_verified` + `replay` 成功 + artifacts hash 未變（混合鎖）。
*   [x] **非 SQL 泛用場景**：已成功實作 `agent-skill-patch-v0.md` 驗證非 SQL 技能代碼之修補閉環。
*   [x] **自評客觀無誇大**：`self-review.md` 已調整自嗨詞彙，並列出 3 個殘留風險。
