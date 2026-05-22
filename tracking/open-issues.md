# System Open Issues Tracking

本檔案追蹤 **Closed Loop Kernel v0** 目前已知且待解決或優化之系統性議題。問題劃分為 Blocker/High 阻礙性問題（當前為 0）以及已記錄並延期處理（Deferred）的中/低度已知風險（當前為 3）。

---

## 1. Blocker / High 優先級問題 (0 筆)

目前無殘留之 Blocker 或 High 優先級阻礙問題。

---

## 2. 已記錄並延期之低優先級已知風險 (Deferred Medium / Low Risks - 3 筆)

以下為已識別但於 v0 原型階段延期處理之已知風險，並附帶具體工程緩解或防禦方案：

| Issue ID | 問題描述與已知風險 | 影響文件 | 嚴重度 | 緩解與防護方案 | 狀態 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ISSUE-001** | **隔離 SQL 沙盒之「資料狀態依賴」風險**：若 Replay 查詢依賴特定生產資料（如金額 > 10000 的訂單），空沙盒會回傳空結果，可能影響 validation_assertions 的精確評估。 | [self-review.md](notes/self-review.md)<br/>[sql-self-healing-v0.md](scenarios/sql-self-healing-v0.md) | **Medium** | 原型開發後，計畫引入「安全去識別化資料複製工具」，重播前安全複製少量脫敏生產資料至 sandbox schema。 | `deferred` |
| **ISSUE-002** | **並行審批部署之「資料庫 DDL 死鎖」風險**：多個變更 Candidate 同時被 Gary 快速連續 Approve 部署時，可能引發 Postgres 並發交易死鎖。 | [self-review.md](notes/self-review.md)<br/>[event-flow-v0.md](spec/event-flow-v0.md) | **Low** | 部署交易執行套用前，在 PostgreSQL 內部執行 `LOCK TABLE artifacts IN EXCLUSIVE MODE`，強制序列化所有部署，防止交叉鎖定。 | `deferred` |
| **ISSUE-003** | **自動斷言 (validation_assertions) 幻覺風險**：AI Supervisor 自動生成的重播斷言可能因過度苛刻而導致正確修復被誤判失敗。 | [self-review.md](notes/self-review.md)<br/>[schema-v0.md](spec/schema-v0.md) | **Low** | v0 階段限制自動斷言僅使用確定性系統指標（如 error_code IS NULL、row_count >= 0），並允許 Gary 在 UI 手動修改與放行。 | `deferred` |

---

## 3. 歷史已解決阻礙問題 (Fixed Issues History)

以下為本原型收斂前已修正之核心設計缺陷：

| Issue ID | 問題描述 | 影響文件 | 嚴重度 | 解決與修正方案 | 狀態 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FIX-001** | **Attempts 唯讀與 UPDATE 的致命衝突**：中途標記 running 且 UPDATE 狀態會被防篡改觸發器攔截而崩潰。 | 所有 spec 與 scenarios 檔案 | **Blocker** | 引入 `attempt_lifecycle_events`，attempts 僅在任務完結時進行 **Only-Once Batch INSERT** 最終結果，徹底消除 UPDATE。 | `fixed` |
| **FIX-002** | **SQL 沙盒隔離脆弱性**：單靠 `search_path` 易被 DROP/TRUNCATE 或 `public.` 前綴繞過。 | `spec/event-flow-v0.md` | **High** | 實施雙沙盒隔離，增設前置 SQL Static Lint 與低特權連線帳號 `sandbox_runner`，收回 public 權限。 | `fixed` |
| **FIX-003** | **部署 Race Condition 變更覆蓋**：並行多 Agent 審批可能導致舊 Prompt 補丁覆蓋新生效變更。 | `spec/event-flow-v0.md` | **High** | 實施「四層部署指紋防線」，部署時悲觀行鎖 `FOR UPDATE` 並樂觀比對當前 hash 是否與 `base_artifact_hash` 一致，不符則 rollback。 | `fixed` |
| **FIX-004** | **非 SQL 場景缺失**：系統缺乏非 SQL 情境證明 kernel 的泛用性。 | 新增 scenario 檔案 | **High** | 建立 `agent-skill-patch-v0.md` 驗證 Python 技能代碼 runtime error 拋出後的 AST 靜態 Linting、subprocess 隔離沙盒驗證與原子部署閉環。 | `fixed` |
