# 研究來源

## YC / AI 原生公司

- Y Combinator Requests for Startups: https://www.ycombinator.com/rfs
  - 重要主題：AI-native service companies、AI Operating System for Companies、Company Brain。
  - 對本 repo 的啟發：公司要變成 AI 可讀、可查、可閉環調整的系統。

- How To Build A Company With AI From The Ground Up: https://readtube.co/videos/how-to-build-a-company-with-ai-from-the-ground-up-EN7frwQIbKc
  - 2026-04-24 的 YC talk 轉錄/摘要頁。
  - 對本 repo 的啟發：AI 原生公司不是單純導入工具，而是讓公司工作流進入 intelligence layer。

- 本地逐字稿：`X_JsIHUfUjc-transcript.txt`
  - 本 repo 的第一手語意來源。
  - 後續架構判斷應優先對齊這份逐字稿，而不是只看二手摘要。

## Hermes Agent

- Hermes Agent GitHub: https://github.com/NousResearch/hermes-agent
  - 用途：確認 repo 結構與官方專案方向。

- Hermes Architecture: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
  - 重點：Entry points -> AIAgent -> tool dispatch / provider resolution / session storage / tool backends。

- Hermes Profiles: https://hermes-agent.nousresearch.com/docs/user-guide/profiles/
  - 重點：每個 profile 有自己的 config、env、SOUL、memory、session、skills、cron、state DB、gateway state。
  - 注意：profile 不是 filesystem sandbox。

- Hermes Subagent Delegation: https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation
  - 重點：`delegate_task` 是同步、短命、fresh-context 子任務，不是 durable queue。

- Hermes Gateway Internals: https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-internals
  - 重點：gateway 是長時間常駐入口，將平台訊息 normalize 後建立 AIAgent，並寫入 session storage。

- Hermes Kanban: https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban
  - 重點：Kanban 是 durable multi-profile collaboration board，適合跨 profile、跨任務、可重試、human-in-the-loop 的工作流。

## GitHub / 開源參考

- Paperclip: https://github.com/paperclipai/paperclip
  - 可參考 agent company UI、agent runs、governance、audit、issue-backed workflow。

- Temporal AI Agent examples: https://github.com/temporal-community/temporal-ai-agent
  - 可參考 durable workflow / replay / long-running agent orchestration。

- OpenAI Agents SDK: https://github.com/openai/openai-agents-python
  - 可參考 agents、handoffs、guardrails、sessions、tracing 等底層設計。

- CrewAI Flows human feedback: https://docs.crewai.com/en/learn/human-feedback-in-flows
  - 可參考 approve / reject / revise 的人工回饋流程。

## 今天的本地 evidence

- `skimm3r918_bot` agent root:
  - `/Users/garyyang/clients/skimm3r918_bot`
  - `/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/skimm3r918_bot`

- Gateway LaunchAgent:
  - `/Users/garyyang/Library/LaunchAgents/com.hermes.gateway.skimm3r918_bot.plist`

- 今日檢查結果：
  - gateway running
  - Telegram connected
  - workspace empty
  - kanban task count zero
  - state DB only contains small test sessions

