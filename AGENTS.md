# Agent Instructions

This repository is the working space for turning 好事發生數位有限公司 into an AI-native company operating system.

The current priority is not to build a generic SEO agent and not to copy the OHYA architecture. The priority is to define a small, durable company kernel that lets real agents work while leaving structured records that can be reviewed, verified, cleaned, and reused.

## How To Talk With Gary (2026-05-27 起,2026-05-27 強化)

**強制規則,不是 default**。所有要給 Gary 看的訊息、回覆、對話、報告、提案,**一律先用白話文 + 情境**,技術詞只能當註解,不能當主幹。

### 必做

1. **先講情境**(everyday 繁體中文)。例:「OP 同事美鳳在 LINE 群打『小弟有國內團嗎?』,bot 沒聽懂 ...」
2. **走流程**:一條訊息 / 一個動作從哪裡進 → 經過誰 → 最後做什麼。
3. **技術詞註解三件套**(同一個括號或註腳寫齊):
   - **使用的程式**:具體的 module / file / table / command,有 `file:line` 最好
   - **關聯性**:跟其他元件什麼關係(e.g. 「跟 Hermes session.db 是兩回事」、「會被 cron 2 讀」)
   - **用途**:這個東西為什麼存在、用來做什麼

   範例:
   > 「資料先存到一張紀錄表(**使用**:`closed_loop_kernel.events`;**關聯**:跟 Hermes 對話歷史 `state.db` 是兩個獨立 DB,前者 PostgreSQL 後者 SQLite;**用途**:給每日 09:00 那條 gemma4 cron 抓 pattern 用)」

4. **引用程式碼用 `file:line` + 一句白話說明那段在做什麼**,不直接貼大段 code。
5. **每個 acronym / schema 縮寫第一次出現要解釋一次**(FK、SoT、CRUD、ETL ...)。

### 不可做

- ❌ 把 function name / table name / column name / commit sha / file path 當句子主詞或訊息開頭(「`apply_candidate` 更新 artifacts 表 ...」、「`b8aa5fa`:8 條 p0 collapse」)
- ❌ 用 table、bullet list、code block、status grid 當訊息開頭 — 必先有 2-3 句白話 + 情境 + 流程
- ❌ 整段技術名詞不解釋就丟過來
- ❌ 引用程式碼貼大段 code 不寫做什麼
- ❌ 用 `default to` / 「視情況」這類軟性語氣 — 本規則是硬規則
- ❌ 認為「Gary 應該看得懂這個」就跳過情境段。看得懂跟需要重新建立 context 是兩件事
- ❌ 寫「Phase 2 開工 ready」這類純狀態詞當主訊息,沒講「為什麼這代表 OK 動下一步、動下一步會發生什麼、Gary 該決定什麼」

### Status report / 進度報告 / commit 摘要 場景(2026-05-29 強化)

進度報告、commit chain 摘要、phase ship 通報、design iteration log 報告 是規則違反高發場景。**任何 table、bullet list、code block、commit sha 都不能當訊息開頭**。

必先 2-3 句白話講清楚:

1. **情境**:什麼事情發生了 / 為什麼要做 / 誰會受影響 / 跟前次 Gary 的指示有什麼關係
2. **流程**:從哪裡開始 → 經過誰 / 哪個檔 / 哪段 → 最後落到哪 → Gary 該不該動 / 動什麼
3. **然後才用 table / bullet 補細節**(細節是註腳)

範例 — 「我把 R18 那條鏈斷掉的問題查清楚了」:

✅ **可以這樣寫**:
> 我剛剛去查我們在乎的那條線:「客戶 LINE 訊息進來 → bot 沒聽懂 → 紀錄一筆失敗 → 之後 gemma4 想推薦改進時要能回頭指出『就是那則訊息惹的禍』」。這條線**現在是斷的** — 我抽真實資料庫 5 筆 failure 出來看,中間那個指針位是空的。
>
> 兩條路:(A)現在去修 V0.2 已上線的 LINE bot 程式 — 但這代表動還在跑的東西,可能弄壞;(B)V0.3 先不靠這條線,改用「拿建議的關鍵字去 failure 訊息預覽裡找」這種弱對應,V0.4 再修。我選 B,你 OK 嗎?

❌ **不可這樣寫**(就是我 2026-05-29 違規那則):
> | Round | Commit | Summary |
> | --- | --- | --- |
> | 1 | e0f5257 | 41 unknowns enumerated + priority |
> | 2 | b8aa5fa | 8 條 p0 spec collapse(codex 7 反提案全採納)|
> 
> Phase 2 開工 ready ...

commit sha / round 編號 / column 名 / table 名 全是註腳,**不准開頭**。

### 範圍

- 適用於:**所有 agent**(Claude, Codex, Antigravity)寫給 Gary 看的任何輸出 — 回覆、摘要、提案、commit message body、PR description、Telegram 推播、文件、註解。
- 不適用於:純 agent-to-agent prompt(例如 `/codex consult` 給 codex 的 brief)— 內部溝通可以技術。
- 但 agent-to-agent 的**最終輸出**如果會給 Gary 看(例如 codex review report 要 forward 給 Gary),整段 forward 之前要由 forwarder agent 改寫成符合本規則的格式。

### 違反處理(2026-05-27 + 2026-05-29 強化)

Gary 看到回覆第一句不是情境 / 技術詞當主幹 / 用 table 或 bullet 或 commit sha 開頭 時,**下列任一訊號**都算違規 trigger,收到後 agent 必須重寫:

- 「白話」
- 「我看不懂」
- 「你寫的這一長串我看不懂」
- 「不要放技術名詞」
- 「用情境跟流程」
- 「太技術」
- 直接指出「你寫的這段我不懂」即可

違規 → agent 必先重寫成符合 § How To Talk With Gary 的版本 → Gary 接受後,將該次違規記到 `closed_loop_kernel.events` event_type=`agent_communication_violation`(將來可以做 retro)。

**meta 原則**:這條規則是 strict 不是 soft。Agent 不能因為「Gary 是 product owner 假設懂技術」就跳過情境段;不能因為「table 比較整齊」就用 table 開頭;不能因為「commit sha 比 git log 看起來精確」就把 sha 當主訊息。 Gary 在路上、在手機、在累的時候,只看得進白話 + 情境 + 流程。

## Doc Discovery Protocol (2026-05-28)

This is a hard rule for Claude, Codex, Antigravity, and any future agent working in this repo.

Before planning, editing, reviewing, or executing any non-trivial task, first read:

```text
docs/plans/INDEX.md
```

The index is the repo's current map. Do not rely on branch memory, old session summaries, or a plan file you happen to remember.

Rules:

- Do read `docs/plans/INDEX.md` before changing architecture, docs, plans, contracts, agent behavior, or department workflows.
- Do state which current plan or contract you are using before making a design decision.
- Do stop and surface the conflict if `docs/plans/INDEX.md` points to a document that contradicts another contract file.
- Do not treat a feature branch plan as canonical unless it is listed in `docs/plans/INDEX.md`.
- Do not create a new plan without updating `docs/plans/INDEX.md` in the same change.

Violation handling:

If Gary says any of the following:

```text
Doc Discovery
最新版在哪
你讀 INDEX 了嗎
找不到最新
```

the agent must stop the current line of work, read `docs/plans/INDEX.md`, restate the relevant current plan files, and retry from that source of truth.

This protocol has the same priority as `## How To Talk With Gary`: both are cross-agent behavior rules, not style suggestions.

## Karpathy Behavioral Guidelines (2026-05-28)

Source: https://github.com/multica-ai/andrej-karpathy-skills (MIT License)

These guidelines apply to Claude, Codex, Antigravity, and any future agent working in this repo.

For trivial tasks, use judgment. Do not turn a one-line answer into a ceremony.

For non-trivial tasks involving architecture, code changes, production behavior, data contracts, branch cleanup, or multi-agent coordination, apply all four principles explicitly:

1. **Think Before Coding** — 不要藏假設、不要藏困惑、surface tradeoffs
2. **Simplicity First** — 50 行夠就別 200,no abstractions for single-use code
3. **Surgical Changes** — 只動該動的,別「順手清掃」
4. **Goal-Driven Execution** — 每步定義 verify check,弱 criteria = constant clarification

Practical rules:

- Before implementing, state the assumptions that could change the design.
- Prefer the smallest useful implementation that can be verified.
- Keep edits scoped to the requested files and behavior.
- Define the verification check before claiming the task is done.
- If the task touches docs or plans, apply `## Doc Discovery Protocol` first.
- If the task changes how agents behave with Gary, also follow `## How To Talk With Gary`.

These guidelines are guardrails. They do not replace the repository contracts in `docs/`; they force agents to read and respect them before acting.

## Current Direction

- Start from real agents and profiles, then collect their traces into the Closed Loop Kernel.
- Every task must preserve structured records for inputs, outputs, sources, artifacts, failures, review, verification, approval, repair, and retention.
- Raw data is not memory. Company memory must be curated, deduplicated, scoped, and eligible for cleanup.
- Profiles must be maintainable: failures can propose profile update candidates, candidates must be sandboxed, reviewed, approved, applied, and old versions archived.
- Growth, SEO, GSC, GA4, social listening, competitor monitoring, YouTube transcript work, and social operations are department applications. They must sit on top of the company contracts.

## Read First

Before changing architecture or docs, read the relevant current files:

- `README.md`
- `docs/company-data-contract-v0.md`
- `docs/hermes-agent-first-architecture.md`
- `docs/2026-05-22-work-summary.md`
- `ai_native_closed_loop_architecture.md`
- `references/ohya-seo-architecture/SNAPSHOT.md`

For the next contract layer, use:

- `docs/company-data-contract-v0.md` as the source contract.
- `docs/agent-profile-registry-v0.md` as the next intended document.

## Boundaries

- Do not treat `references/ohya-seo-architecture/` as code to run or migrate. It is a reference snapshot only.
- Do not import OHYA-specific names, paths, WordPress assumptions, tokens, or runtime data into this repo.
- Do not touch credentials, auth files, live runtime logs, production databases, or Hermes runtime state.
- Do not let one profile execute, review, approve, and apply its own work.
- Do not turn every sub-agent role into a permanent profile. Permanent profiles need a registry entry and clear responsibility.

## Documentation Workflow

- For new architecture documents, first propose design direction and section structure.
- Wait for Gary approval before writing the file.
- Keep documents practical: define records, fields, gates, ownership, lifecycle, and non-goals.
- Prefer small contracts that can later be implemented and tested over broad company-brain essays.
- Keep facts, assumptions, and future plans separate.

## Branch And Commit Workflow

- Keep `main` clean, readable, and handoff-ready.
- For small documentation-only changes, direct commits to `main` are acceptable after diff review.
- For formal architecture documents, prototype changes, code changes, or multi-agent work, create a short-lived branch first.
- Do the work, review `git diff`, run relevant checks, then commit on the branch.
- Merge back to `main` only after Codex review confirms the branch is coherent and tests or document consistency checks pass.
- Antigravity should not commit or merge unless Gary explicitly asks for that.

## Codex And Antigravity Workflow

- Codex is the controller, planner, reviewer, and committer.
- Antigravity is the bounded executor. It should follow Codex task briefs and should not expand scope by itself.
- Antigravity may use subagents for read-only mapping, review, and consistency checks.
- Do not run multiple Antigravity writers against the same file in the same working tree. Use one writer plus reviewer subagents, or use isolated worktrees when true parallel edits are required.
- Antigravity must not commit unless Gary explicitly asks for that.
- Codex must verify Antigravity output with `git status`, `git diff`, and relevant checks before accepting work.

Detailed operating rules live in `docs/antigravity-supervision-workflow.md`.

## Verification

When code or prototype behavior changes, run the relevant local checks before claiming completion:

```bash
python3 -m unittest discover -s tests
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
```

For documentation-only changes, at minimum inspect the diff and verify that the document does not contradict `docs/company-data-contract-v0.md`.
