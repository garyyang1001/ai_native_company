# 2026-05-22 工作總結

## 起點

今天的核心目標是把「AI Native Company / Closed Loop」從文件概念變成本地可跑、可測、可看懂的 prototype。

原始素材包括：

- `X_JsIHUfUjc-transcript.txt`：最早的對話影片逐字稿。
- `ai_native_closed_loop_architecture.md`：AI 原生閉環架構入口文件。
- `antigravity_closed_loop_workflow_prompt.md`
- `antigravity_continuous_tracking_goal.md`

## 已完成

### 1. Closed Loop Kernel v0 prototype

新增本地 Python prototype：

- `closed_loop_kernel/store.py`
- `closed_loop_kernel/engine.py`
- `closed_loop_kernel/demo.py`
- `closed_loop_kernel/postgres.py`
- `closed_loop_kernel/sandbox.py`
- `closed_loop_kernel/views.py`
- `closed_loop_kernel/http_app.py`

目前可跑的流程：

```text
attempt started
-> attempt running
-> attempt finished
-> failure captured
-> candidate proposed
-> sandbox replay
-> human approval
-> candidate applied
```

### 2. 資料模型

目前 prototype 用 SQLite 模擬 PostgreSQL 行為：

- append-only lifecycle
- attempts / failures / candidates / replays / approvals / artifacts
- foreign key
- 防止 update/delete 的 trigger
- orphan lifecycle reconciliation

另有 PostgreSQL DDL renderer，輸出對應 schema、FK、append-only trigger 與 orphan view。

### 3. Sandbox / replay

已做第一版 Python sandbox：

- AST lint 阻擋危險 import / function。
- subprocess 隔離執行 candidate patch。
- replay 結果會寫回 kernel。

目前還不是 OS-level sandbox，不能視為 production 安全邊界。

### 4. 人類可讀 UI

本地 HTTP app 已有：

- `/events`
- `/events/:id`
- `/improvements`
- `/approvals`

依 Gary 的回饋，已把原本人類看不懂的 raw table name、UUID、英文技術欄位，改成比較接近人工審核的繁中標籤。

例如：

- `attempt_lifecycle_events` 改成 `任務開始`、`執行中`、`任務完成`
- `Event Detail` 改成 `執行詳情`
- `Status: failed` 改成 `執行失敗`
- `/approvals` 支援 `批准並套用` / `拒絕`

### 5. 測試

目前測試覆蓋：

- closed loop kernel engine
- demo scenario
- HTTP routes
- PostgreSQL schema renderer
- Python sandbox
- human-readable views

最後一次驗證命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

結果：

```text
Ran 23 tests
OK
```

### 6. Tracking 文件清理

已清理 tracking/prototype docs 裡過度誇張或容易誤導的字眼：

- `100%`
- `水密級`
- `完全收斂`
- `符合度`
- `ALL PASS`

目前 tracking 文件比較像工程狀態，而不是宣傳文案。

## 今天的重要架構轉向

Gary 提出一個關鍵直覺：

> 其實應該反過來做？agent 先建好，再把它們統一接到大腦。

這個方向成立，而且比「先蓋一顆大腦」更務實。

新的判斷：

```text
agent-first
不是 brain-first
```

也就是：

1. 先建立真正會工作的 agent。
2. 讓 agent 在真實任務中留下 session、task、artifact、failure、approval。
3. 再把這些資料回收到 Closed Loop Kernel。
4. Company Brain 從這些工作痕跡中長出來。

但不能讓每個 agent 亂寫資料，所以仍需要一個很薄的 kernel contract：

- agent 是誰
- 接了什麼任務
- 用了哪些工具
- 產出什麼 artifact
- 哪裡失敗
- 怎麼修
- 有沒有 replay
- 誰批准
- 最後有沒有 apply

## 本地 Hermes agent 檢查

今天確認了一個乾淨 Hermes Telegram agent：

```text
/Users/garyyang/clients/skimm3r918_bot
```

實體位置：

```text
/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/skimm3r918_bot
```

狀態：

- Profile：`skimm3r918_bot`
- Telegram：`@skimm3r918_bot`
- Gateway：running
- PID：`27011`
- Provider：`openai-codex`
- Model：`gpt-5.5`
- Workspace：`/Users/garyyang/workspace/skimm3r918_bot`
- Workspace 目前是空的
- Kanban DB 目前無任務
- state DB 只有少量測試 session/message

結論：

這個 agent 已啟動、能連 Telegram，但尚未開始正式任務。它適合作為第一個 agent-first 試點入口，但目前不應急著讓它產出。

## 下一步

建議下一階段先做設計，不直接派工：

1. 明確定義 `skimm3r918_bot` 作為入口 agent 的責任。
2. 設計 worker profiles：
   - research
   - builder
   - reviewer
   - ops
   - memory/brain curator
3. 用 Hermes Kanban 作為 durable task bus。
4. 讓 Closed Loop Kernel 匯入：
   - Hermes `state.db`
   - Hermes `kanban.db`
   - workspace artifacts
   - approval / failure / replay events
5. 再做第一個小任務，而不是直接讓 agent 接大任務。

