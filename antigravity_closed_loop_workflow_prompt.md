# Antigravity Prompt：Closed Loop Kernel v0 工作閉環

你現在要基於本資料夾內兩份文件工作：

- `/Volumes/Hermes System/HermesArchive/Gary/ai_native_closed_loop_architecture.md`
- `/Volumes/Hermes System/HermesArchive/Gary/X_JsIHUfUjc-transcript.txt`

重要修正：

- `typeless` 是誤打，完全忽略，不要再以 Typeless 為前提。
- 不要做 employees / 員工資料庫 demo。Gary 覺得這個方向不對。
- 不要把 YC 演講中的 query example 直接照抄成玩具 demo。
- 目標不是炫技 demo，而是設計可長期演化的最底層 closed loop foundation。
- PostgreSQL 可以是 source of truth；JSONL 只能是 export/debug，不是主記憶層。
- 歷史不可竄改：第一次失敗就是失敗，修好後要新增 replay / verification record，不得回改舊紀錄。
- 自動 code patch / DDL migration 不可直接套用；必須走 proposal → sandbox/replay → approval gate → apply。

---

## 你的工作方式：Closed Loop Research / Design / Test Loop

請不要一次產出自信滿滿的終稿。你要用「持續思考、研究、修正、驗證」的方式工作，直到規格足夠清楚可開工。

每一輪都要留下可見產物，不要只說你想了什麼。

### Loop 0：讀取與對齊

1. 讀完整份 `ai_native_closed_loop_architecture.md`。
2. 讀 `X_JsIHUfUjc-transcript.txt`，至少定位並引用這幾個概念：
   - sensor layer
   - record everything
   - make organization legible to AI
   - monitoring query failures
   - self-improvement loop
   - tools / skills / DB view / index
   - human supervision / quality gate
3. 產出 `notes/source-alignment.md`：
   - 文件目前哪些地方對齊逐字稿？
   - 哪些地方還滑向 toy demo？
   - 哪些地方缺工程可開工細節？

### Loop 1：外部研究，不要只靠直覺

使用 Antigravity 的 browser-in-the-loop 能力，查公開資料。請低頻、只讀，不登入、不發送、不繞過限制。

至少研究這些方向：

1. event sourcing / audit log / append-only history
2. workflow engines / durable execution（例如 Temporal 類概念即可，不需照搬）
3. evals / replay / regression testing for agents
4. human approval gates / change management
5. self-healing systems / autonomous software development guardrails

產出 `notes/research-findings.md`：

- 每個來源 3–5 行摘要
- 對本專案的啟發
- 哪些概念該採用
- 哪些概念先不要採用
- 附來源 URL

### Loop 2：重新定義最底層資料模型

請重新設計 Closed Loop Kernel v0 的核心 schema。

不要以 SQL query demo 為主角。主角應該是抽象事件模型：

- event
- attempt
- tool_call
- artifact
- decision
- failure
- improvement_candidate
- replay
- approval
- policy_gate

要求：

1. 說明每張表存在的原因。
2. 說明哪些欄位是 v0 必要，哪些可以 v1 再做。
3. 說明 append-only / immutable history 怎麼落地。
4. 說明 status 可以被更新的範圍：例如 failure 可以從 open → resolved，但不能把 failed attempt 改成 success。
5. 產出 `spec/schema-v0.md`。

### Loop 3：事件流設計

設計最小閉環事件流：

```text
user/task input
→ create event
→ create attempt
→ run tool/action
→ success or failure
→ if failure: create failure
→ supervisor RCA
→ create improvement_candidate
→ sandbox/replay
→ approval_required
→ human approve/reject
→ apply if approved
→ create verification/replay record
→ update operating knowledge / backlog
```

要求：

1. 每一步明確寫入哪張表。
2. 每一步誰負責：agent / supervisor / human DRI / deterministic tool。
3. 每一步是否需要 approval。
4. 每一步失敗時怎麼記錄，不可以吞錯。
5. 產出 `spec/event-flow-v0.md`。

### Loop 4：最小 UI / HTML View

設計最小 HTML UI，不要做大 dashboard。

只要 4 個 view：

1. `/events`：事件列表
2. `/events/:id`：單一事件 timeline
3. `/improvements`：改進候選列表
4. `/approvals`：待審批項目

要求：

- 每個 view 顯示哪些欄位
- 哪些 action button 可用
- 哪些 action 必須 disabled，直到 sandbox/replay 成功
- UI 需要顯示原始失敗與後續 replay，而不是覆蓋歷史
- 產出 `spec/html-views-v0.md`

### Loop 5：Scenario 1 只能當驗證案例

SQL self-healing 可以保留，但只能作為 Scenario 1，用來驗證 kernel。

請重新設計 Scenario 1：

- 不要 employees table。
- 可用更中性的 domain，例如 `documents` / `tasks` / `events`，或乾脆用 kernel 自己的資料做查詢。
- 重點不是 query demo，而是驗證：failure → improvement_candidate → replay → approval → verification。
- 產出 `scenarios/sql-self-healing-v0.md`。

### Loop 6：自我檢查與修正

每一輪完成後，都要自我檢查是否犯了這些錯：

- 是否又回到 employees demo？
- 是否又把 JSONL 當 source of truth？
- 是否竄改歷史紀錄？
- 是否讓 LLM 自動套用 code / DDL 而沒有 approval gate？
- 是否缺 replay / verification？
- 是否缺 browser research evidence？
- 是否缺可開工的 schema / event flow / UI spec？

產出 `notes/self-review.md`，列出：

- 通過項目
- 不足項目
- 下一輪修正

至少跑 2 輪修正後，才產出最終文件。

---

## 最終輸出要求

請在資料夾內產出：

```text
/Volumes/Hermes System/HermesArchive/Gary/
  notes/
    source-alignment.md
    research-findings.md
    self-review.md

  spec/
    closed-loop-kernel-v0.md
    schema-v0.md
    event-flow-v0.md
    html-views-v0.md
    acceptance-criteria-v0.md

  scenarios/
    sql-self-healing-v0.md
```

最終 `spec/closed-loop-kernel-v0.md` 必須包含：

1. 一句話定義最底層是什麼。
2. 跟 YC 逐字稿的對齊表。
3. PostgreSQL source-of-truth 原則。
4. append-only / 不竄改歷史原則。
5. schema 摘要。
6. event flow 摘要。
7. approval/replay/sandbox 流程。
8. 最小 HTML views。
9. Scenario 1 的定位。
10. v0 acceptance criteria。

請開始前先列出你的工作計畫與要查的外部資料方向；接著直接執行研究、修正文件與自我檢查。