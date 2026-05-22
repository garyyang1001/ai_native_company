# Minimal HTML UI Specification (Loop 4)

本文件定義 **Closed Loop Kernel v0** 的極簡審批與審計前端畫面（Minimum HTML UI）。捨棄複雜龐大的儀表板，專注於提供人類 DRI 最直覺的系統事件流追蹤、失敗對比以及安全的變更審批介面。

---

## 1. 視覺設計與排版系統 (CSS Design System)

UI 使用高雅的極簡暗色調（harmonious dark-mode palette）進行視覺設計，採用現代字型、玻璃擬態（glassmorphism）邊框以及流暢的微動畫交互。

```css
:root {
    --bg-main: #0B0F19;         /* 極暗太空藍 */
    --bg-card: #151D30;         /* 深卡片藍 */
    --accent: #38BDF8;          /* 亮天藍 (主色調) */
    --accent-success: #34D399;  /* 薄荷綠 (成功/通過) */
    --accent-failed: #F87171;   /* 珊瑚紅 (失敗/報錯) */
    --accent-warn: #FBBF24;     /* 琥珀黃 (等待審批) */
    --text-primary: #F3F4F6;    /* 近純白 */
    --text-secondary: #9CA3AF;  /* 灰字 */
    --border-color: #2D3748;    /* 卡片邊線 */
    --font-family: 'Outfit', 'Inter', sans-serif;
}
```

---

## 2. 四大核心檢視畫面 (Core Views)

### 檢視一：系統事件列表 (`/events`)
*   **用途**：以唯增時間軸（Chronological Log）呈現系統發生的所有感測事件，方便即時稽核。
*   **顯示欄位**：
    *   `Timestamp`：事件時間（顯示為本地時間 + 相對時間，例如：*3 分鐘前*）。
    *   `Source`：觸發源（帶有不同視覺標籤，如 `[UI]`、`[Supervisor]`、`[Engine]`）。
    *   `Event Type`：事件類型（帶有語意色彩，如 `query_received` (藍色)、`attempt_failed` (紅色)、`approval_granted` (綠色)）。
    *   `Payload Snippet`：JSONB 格式的簡短摘要（點擊展開完整 JSON）。
*   **可用 Actions**：
    *   **"Detail" 按鈕**：導向 `/events/:id` 查看此事件的完整 Timeline 與鏈路。
    *   **"Filter" 下拉選單**：依 Event Type、Source 篩選。

---

### 檢視二：事件關聯 Timeline 畫面 (`/events/:id`)
*   **用途**：以垂直時間軸（Vertical Timeline）串聯該事件所觸發的整個生命週期（例如：`Event` ➔ `Attempt` ➔ `Failure` ➔ `Candidate` ➔ `Replay` ➔ `Approval`）。這能清楚展現「歷史不可篡改，但新 Replay 能證明修復」的核心哲學。
*   **顯示欄位與視覺結構**：
    *   **Node 1: Event 節點**（根事件）：顯示原始 user 請求輸入。
    *   **Node 2: Attempt 節點**：
        *   若 `status='failed'`：以紅色警記標註，並在下方以程式碼區塊印出 `error_message`。
        *   **歷史事實不可被覆蓋**：即使後續修復成功，這個節點也永遠維持紅色。
    *   **Node 3: Failure 節點**：顯示 Failure ID, Status (`open` 或 `resolved`)。
    *   **Node 4: Candidate 節點**（若有）：顯示 AI 生成的 Diff/DDL。
    *   **Node 5: Replay 節點**（若有）：
        *   顯示 Sandbox Replay 的結果 (`success` 或 `failed`)。
    *   **Node 6: New Attempt 節點**（修復後重試的結果）：顯示最終在 Production 重播成功的綠色節點。
*   **可用 Actions**：
    *   **"Inspect Artifacts" 按鈕**：查看該 Attempt 執行當下所處的版本資產。

---

### 檢視三：改進候選列表 (`/improvements`)
*   **用途**：檢視系統中所有被 AI Supervisor 產生的優化提案與 Bug 修復補丁。
*   **顯示欄位**：
    *   `ID`：Candidate UUID。
    *   `Associated Failure`：關聯的失敗 ID 與失敗摘要。
    *   `Patch Type`：補丁類型（`prompt_update`, `db_migration`, `code_patch`）。
    *   `Proposed By`：提出改進的 Agent 識別。
    *   `Sandbox Replay`：沙盒重播結果狀態（`Passed` 或 `Failed`）。
    *   `Candidate Status`：當前狀態（如 `draft`, `sandbox_verified`, `applied`）。
*   **可用 Actions**：
    *   **"View Diff"**：彈出 Modal 對比原始 Prompt/Schema 與優化後的 Diff。

---

### 檢視四：待審批項目控制台 (`/approvals`)
*   **用途**：人類 DRI (Gary) 的實體控制閘門。這是最關鍵的安全控制台。
*   **顯示欄位與排版**：
    *   **失敗摘要區**：印出導致此次失敗的 `attempts.input` 與報錯 `error_message`。
    *   **對比視窗 (Side-by-Side Diff)**：
        *   左側：當前生產環境的 Artifacts (如舊 SQL prompt, 舊 Schema)。
        *   右側：AI 產生的 `artifact_diff`（高亮標註新增、修改、刪除行）。
    *   **沙盒重播報告區**：
        *   列出重播執行的 Sandbox Schema。
        *   列出斷言檢驗結果（例如：`Row Count > 0` ➔ `[ PASS ]`）。
    *   **DRI 意見欄**：提供輸入框讓 Gary 填寫批註。
*   **可用與不可用的 Actions 按鈕（審批阻斷狀態）**：
    *   🔴 **"Approve & Deploy" 按鈕**：
        *   **狀態：DISABLED** ➔ 若 `replays.status != 'success'`（即 sandbox 重播尚未成功，或失敗），此按鈕為禁用狀態，背景為灰色，滑鼠游標為 `not-allowed`。
        *   **狀態：ENABLED** ➔ 只有在 `replays.status = 'success'` 且 `candidate.status = 'sandbox_verified'` 時，按鈕才轉為高亮薄荷綠，開放點擊。
    *   ⚪ **"Reject" 按鈕**：永遠保持 Enabled。點擊後將候選方案設為 `rejected`，將 failure 退回 open 狀態。

---

## 3. UI 交互狀態機 (UI Interactive State)

以下是審批頁面中「Approve & Deploy」按鈕的狀態切換邏輯，以確保沒有通過沙盒測試的程式碼絕對無法被人類誤點部署：

```text
[ AI 偵測失敗 ] ──> 生成 Draft Candidate ──> 畫面顯示: [ Replay 未執行 ] ➔ [ Approve 按鈕禁用 ]
                               │
                               ▼
                       [ 執行 Sandbox Replay ]
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
     Replay Status: FAILED                 Replay Status: SUCCESS
     Candidate: draft                      Candidate: sandbox_verified
     [ Approve 按鈕禁用 ]                   [ Approve 按鈕啟用 ]
     (顯示詳細 Replay 報錯)                     (薄荷綠高亮，可一鍵部署)
```
