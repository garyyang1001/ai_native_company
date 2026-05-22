# Gary

這個 repo 的目標是把「AI 原生公司」從概念推進成可跑、可驗證、可逐步接上真 agent 工作流的本地系統。

目前方向不是先做一顆巨大的公司大腦，而是先讓真實 agent 工作，然後把它們留下的任務、過程、錯誤、成果與審批紀錄收回同一個 closed-loop kernel。大腦是從 agent 的工作痕跡長出來，不是先畫完整再要求 agent 配合。

## 目前主線

1. Closed Loop Kernel v0
   - 本地 SQLite prototype，模擬 PostgreSQL 版本的 append-only lifecycle、failure、candidate、replay、approval、apply 流程。
   - 本地 HTML UI：`/events`、`/events/:id`、`/improvements`、`/approvals`。
   - 測試覆蓋核心資料模型、approval route、view rendering、PostgreSQL DDL renderer、Python sandbox。

2. Agent-first 架構
   - 先以乾淨 Hermes Telegram agent `skimm3r918_bot` 當入口候選。
   - 不急著讓 agent 產出，先研究主入口 agent + 多個 profile worker 是否可行。
   - 初步判斷：可行，但 durable 多 agent 工作應該走 Hermes Kanban / profile worker，而不是只靠短命的 `delegate_task`。

3. Company Brain
   - 不是聊天記憶。
   - 是從 agent sessions、kanban tasks、workspace artifacts、failures、replays、approvals 匯入而成的查詢、回放、審核、學習層。

## 重要文件

- [今日工作總結](docs/2026-05-22-work-summary.md)
- [Hermes agent-first 架構研究](docs/hermes-agent-first-architecture.md)
- [Company Data Contract v0](docs/company-data-contract-v0.md)
- [研究來源](docs/research-sources.md)
- [OHYA SEO 架構參考快照](references/ohya-seo-architecture/SNAPSHOT.md)
- [Closed Loop Kernel prototype](PROTOTYPE.md)
- [原始架構入口](ai_native_closed_loop_architecture.md)
- [逐字稿](X_JsIHUfUjc-transcript.txt)

## 本地驗證

```bash
python3 -m unittest discover -s tests
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
```

開啟本地 UI：

```text
http://127.0.0.1:8765/events
```

## 邊界

- 目前 prototype 不碰 production DB。
- 目前沒有讓 `skimm3r918_bot` 開始做正式任務。
- Hermes auth、token、logs、profile DB、kanban DB 不進 repo。
- PostgreSQL adapter 目前是 DDL renderer，尚未做 live integration。
- Company Brain 還是架構方向，下一步才會接真 agent traces。
