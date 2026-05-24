# Code is Law — Closed Loop Kernel 根本原則

**版本**：v0
**確立日期**：2026-05-24
**確立 context**：OHYA 整合第一版 demo 提了一個 `prompt_update` candidate 建議「遇到連線錯誤先 sleep 5 秒再重試」。Gary 拒絕並指出此建議違反原始架構 — retry 邏輯不該寫在 prompt 裡。本文件把這個糾正升級為所有後續設計的根本原則。

---

## 1. 原則

> **所有 agent 的工作流程（control flow）行為必須由程式碼規範（deterministic code）。Prompt 只負責 task-level 業務內容指引，不規範 control flow。**

具體展開：

### 1.1 必須由程式碼定義的事項（Code 範圍）

| 類別 | 例子 |
|---|---|
| **重試策略** | retry 次數、retry 間隔、exponential backoff、ceiling |
| **超時設定** | HTTP timeout、worker timeout、queue TTL |
| **頻率限制** | rate limit、concurrency limit、burst size |
| **資料驗證** | schema check、type check、range check、enum 約束 |
| **部署校驗** | 四道指紋校驗、FOR UPDATE row lock、hash mismatch rollback |
| **安全檢查** | SQL/Python lint 黑名單、sandbox 隔離、低權限角色 |
| **失敗處理流程** | crash → failure → candidate → replay → approval |
| **冪等性** | deterministic UUID、idempotency_key、checkpoint |
| **稽核 / 紀錄** | append-only trigger、不可篡改歷史、每一步寫進 events 表 |

### 1.2 可以放進 prompt 的事項（Prompt 範圍）

| 類別 | 例子 |
|---|---|
| **業務知識** | 「文章標題不應超過 60 字元」「我們是 B2B SEO 行銷代理商」 |
| **語氣 / 風格** | 「全程繁體中文台灣用語」「直接、精簡、可執行」 |
| **任務指引** | 「先查 GSC 找出排名下滑頁面，再提建議改寫方向」 |
| **領域範例** | 「以下是好標題範例：...」 |
| **業務規則** | 「客戶資料絕不可外洩」「破壞性動作先回報 Gary」 |
| **角色定位** | 「你是 SEO content writer」 |

---

## 2. 為什麼這條原則重要

### 2.1 Prompt 不具備 deterministic 保證

LLM 對同樣 prompt 兩次回應可能不同。把 control flow 交給 prompt 等於：
- 同樣的失敗，兩次處理方式可能不一樣
- 沒辦法做 unit test / regression test
- 沒辦法在 sandbox 真實 replay

Gary kernel 的 11 表 schema 設計核心是「失敗發生時，有完整的 deterministic 路徑可以從 root cause 找到 fix 並驗證」。Prompt 為基底的 control flow 直接打破這個保證。

### 2.2 spec/closed-loop-kernel-v0.md 的 sandbox 設計只對 code/sql 有效

我們的兩個 sandbox：
- `PythonSandbox`：真實 subprocess + rlimit + AST lint，**真的會跑** candidate 程式碼
- `SqlSandbox`：真實低權限角色 + 臨時 schema，**真的會跑** candidate SQL

`prompt_update` 沒有真實 replay 機制 — 沒辦法「模擬跑這個新 prompt」確認行為改變。要驗證新 prompt 只能：
- 真的呼叫 LLM（花錢 + indeterministic）
- 或人類目視判斷（沒有客觀標準）

**所以 prompt_update 永遠是「最弱的一類修正」**，不能當主力。

### 2.3 違反這條原則的歷史教訓

業界已知反例：
- 早期 AutoGPT / BabyAGI 試圖讓 LLM 「自我改 prompt 形成 agent loop」→ 結果 prompt drift、行為不穩、無法 reproduce
- LangChain 早期讓 LLM 決定「要不要 retry」、「要不要 escalate」→ 結果同樣任務每次走不同路徑

正確做法：
- LLM 做 **task-level 判斷**（這篇文章哪段需要改寫？）
- Code 做 **control flow**（retry / timeout / 部署校驗）

---

## 3. 對 `improvement_candidates.patch_type` 三類的重新定位

| patch_type | 用途 | sandbox 驗證 | 主力程度 |
|---|---|---|---|
| **`code_patch`** | 改 Python 程式碼（control flow、retry、validation、安全） | ✅ PythonSandbox 真實跑 | ⭐⭐⭐⭐⭐ **主力** |
| **`sql_patch`** | 改 SQL（schema、query、migration） | ✅ SqlSandbox 真實跑 | ⭐⭐⭐⭐⭐ **主力** |
| **`prompt_update`** | 改業務內容指引（語氣、業務知識、範例） | ⚠️ 只有 lint，無 behavior replay | ⭐⭐ **次要、限業務內容** |

`prompt_update` 不可用於：
- ❌ 改 retry / timeout 行為（這該 code_patch）
- ❌ 改安全檢查 / 部署規則（這該 code_patch + spec 改動）
- ❌ 改 schema / 資料驗證（這該 code_patch 或 sql_patch）

`prompt_update` 可用於：
- ✅ 「請把標題從 8 字改成 10-15 字」
- ✅ 「請改用更友善的客服語氣」
- ✅ 「新增這個業務規則例子到 system prompt」

---

## 4. 對 FailureAnalyzer 模板的具體要求

每一類 failure_type 對應的修正方向：

| failure_type | 第一選擇 | 不可選擇 |
|---|---|---|
| `crash` | `code_patch` — 加 try/except、改 HTTP client 設定、改 retry decorator | ~~`prompt_update` 加「請小心 crash」~~ |
| `timeout` | `code_patch` — 改 timeout config、改 chunk size、加 exponential backoff | ~~`prompt_update` 加「請別 timeout」~~ |
| `spawn_failed` | `code_patch` — 修 profile config、修 launchctl plist、修 venv 依賴 | ~~`prompt_update` 加「請正確啟動」~~ |
| `gave_up` | `code_patch` — 改 max_retries config、加 escalation hook | ~~`prompt_update` 加「請別放棄」~~ |
| `failed`（一般） | 視 root cause；多數還是 `code_patch` 或 `sql_patch` | prompt_update 只限業務行為微調 |

---

## 5. 對 spec/closed-loop-kernel-v0.md 既有設計的影響

這條原則**不會修改 schema**（11 表 + governance 層 3 表都不動），只**約束 candidate 的內容**：
- `improvement_candidates.patch_type` 的選擇必須符合本原則
- FailureAnalyzer（或未來真實 LLM analyzer）的 prompt 必須明文要求「優先 code_patch / sql_patch」
- approvals 流程（人類批准閘門）必須教育 Gary 拒絕違反原則的 candidate

---

## 6. 自我紀錄要求

連這條原則本身的「確立 context」（OHYA 第一版 demo 的設計錯誤）也必須寫進 ohya_kernel 的 events 表，event_type = `infrastructure_issue` 或 `meta_failure`。理由：

> 「AI 原生公司就是自我修復 + 自我學習 + 每一步都紀錄」— Gary, 2026-05-24

我們自己（kernel 設計者）犯的設計判斷錯誤也算「kernel 運行中發生的事件」，也該進稽核軌跡。

---

## 7. 反例 — 第一版 OHYA demo 提的錯誤 candidate

**candidate id**: `0306473b-7af7-45ec-9545-538493b0237d`
**patch_type**: `prompt_update`（❌ 違反本原則）
**target**: `ohya.agent_profiles.system_prompt`
**proposed_content** 摘要: 「在 agent system prompt 末尾加入：遇到 ConnectionError 先 sleep 5 秒再重試」

為什麼違反：
1. retry 邏輯屬於 control flow，必須由程式碼規範
2. OHYA hermes-agent 的 kanban schema 已內建 `consecutive_failures` + `max_retries` 欄位 — 重複 + 衝突
3. 「sleep 5 秒」對 60 秒 Zeabur API timeout 來說太短，沒解決 root cause
4. 用 prompt_update 等於放棄 sandbox 真實驗證

正確的 candidate 應該是 `code_patch`：
- target: 真實的 cms-draft-executor Python 程式碼（bin/ 內某 script）
- proposed_content: HTTP client 加 exponential backoff decorator、提高 timeout、加結構化錯誤回報
- sandbox: PythonSandbox 真實跑改後程式碼 + assert N 次 ConnectionError 後第 N+1 次 success

第一版 candidate 已於 2026-05-24 被 Gary 拒絕並重做為 code_patch 版（見 docs/ohya-integration-v0.md 後續紀錄）。
