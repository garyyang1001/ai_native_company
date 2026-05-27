# docs/plans/ Index

**Canonical source of all planning docs: `main` branch.** Feature branches may contain working drafts but **must merge to main before other agents depend on them**.

This index is updated whenever a plan is added, superseded, or archived. If you're an agent picking up a task, **read this file first**.

---

## Read-first protocol (新 agent 接 task 固定流程)

1. `git switch main && git pull --ff-only origin main`
2. Read `AGENTS.md` — 工作偏好 + 溝通規則(How To Talk With Gary)
3. Read **this `docs/plans/INDEX.md`** — 你現在在讀
4. Read `docs/company-data-contract-v0.md` + `docs/agent-profile-registry-v0.md` — 公司契約 + profile 註冊
5. Drill into 跟當前 task 直接相關的具體 plan(往下看 Current canonical 區)

---

## Current canonical plans

### OP Bot (operations 部門)

| Plan | Status | 一行說明 |
|---|---|---|
| `2026-05-27-learning-loop-design-v0.md` | **v0.1 draft** | OP learning loop 4 元件設計:failure writer / candidate proposer / materializer / runtime SoT。含 Codex review 吸收的 PII 最小化、correlation id、sandbox allowlist |
| `2026-05-26-op-kernel-db-operations-v2.md` | **v2.1 canonical** | OP kernel DB schema + 4 cron + backup + 14-step lifecycle + pattern_routes 退場機制 |
| `2026-05-26-op-kernel-c1-c4-execution-report.md` | **execution log** | C1-C4 cron + backup script 真實落地紀錄,Wave 1+2 fixes |

### Marketing Agent (marketing 部門)

| Plan | Status | 一行說明 |
|---|---|---|
| `2026-05-26-marketing-agent-bootstrap.md` | **bootstrap canonical** | marketing-agent profile 啟動規劃,M1-M5 任務序列 |

### Cross-department / Architecture

| Plan | Status | 一行說明 |
|---|---|---|
| `2026-05-26-wannavegtour-full-company-bot-map-v2.md` | **v2 canonical** | 全公司 bot map(α/β/γ/δ/ε 5 條工作線)+ 部門整合架構 |
| `2026-05-26-hermes-wannavegtour-integration-plan-v1.md` | **v1 canonical** | Hermes ↔ wannavegtour 整合主計畫,鎖 α 路徑(Hermes native) |

---

## Superseded (留歷史脈絡,不當主來源)

| Plan | Superseded by | Why |
|---|---|---|
| `2026-05-25-hermes-wannavegtour-integration-plan-v0.md` | `2026-05-26-hermes-wannavegtour-integration-plan-v1.md` | v1 fully replaces v0(基礎+能力 roadmap 修正) |
| `2026-05-26-op-kernel-db-operations.md` | `2026-05-26-op-kernel-db-operations-v2.md` | v2.1 修了 3 個 schema drift(A/B/C),Codex review 後重寫 |
| `2026-05-26-op-bot-hermes-harness-spec.md` | (B1 redesign 2026-05-27) | 6-tool harness 已 retire(`~/.hermes/plugins/op-assistant-tools/` 移到 retired-plugins),改 B1 Python-first 路由。spec 保留當 Layer-2 LLM fallback 實驗種子 |
| `2026-05-26-op-kernel-codex-execute-plan.md` | (executed) | C1-C4 已完成,執行紀錄在 `c1-c4-execution-report` |

---

## Handoffs (時間點快照,讀完即過)

| Doc | 用途 |
|---|---|
| `docs/handoffs/2026-05-23-private-dev-handoff.md` | dev session handoff 2026-05-23 |
| `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md` | OP bot 主 handoff,8 個 pending tasks 分類 |
| `docs/handoffs/2026-05-25-wannavegtour-session-context.md` | 2026-05-25 架構決定 session context |

---

## Foundation docs (不在 plans/ 但相關)

| Doc | 用途 |
|---|---|
| `AGENTS.md` | 跨 agent 工作偏好 + How To Talk With Gary 硬規則 |
| `docs/company-data-contract-v0.md` | L1 資料契約:8 種 canonical record + 7 種 failure_type + ... |
| `docs/agent-profile-registry-v0.md` + `data/agent-profile-registry-v0.json` | L2 profile 登記 + 15 個 growth-intelligence 部門 profile |
| `spec/closed-loop-kernel-v0.md` | L5 closed-loop kernel 主規格書 |
| `ai_native_closed_loop_architecture.md` | 5-layer 架構入口 + 規格書索引 |

---

## Maintenance rules(誰違反 = Gary 回「找文件」二字)

任何 agent 寫新 plan / 標 superseded / 加 archive 都必須**同步更新本檔**:

1. **寫新 plan** → 加入 Current canonical 區的對應部門 / Cross-dept 子段
2. **替換舊 plan** → 把舊 entry 從 Current 搬到 Superseded,標 `Superseded by:` + 一行 why
3. **完全廢棄** → 之後可能移到 `docs/archive/`(目前未啟用,未來機制)
4. **新部門誕生** → 在 Current canonical 加新子段

每份 plan 之後也該加 frontmatter(status / version / supersedes / last_updated / canonical_for),目前先用 INDEX 統一管理,frontmatter 之後再批次補。
