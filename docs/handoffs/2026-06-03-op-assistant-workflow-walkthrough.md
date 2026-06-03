# OP Assistant — 整套 Workflow 白話文 + 程式對照

Date: 2026-06-03
Type: walkthrough (新 agent / 新 session 接 task 前讀這份)
Companion to: `docs/plans/2026-05-28-system-state-overview.md` (canonical snapshot)

## Purpose

system-state-overview 給的是 snapshot + Mermaid 流程圖；本檔給的是「**像跟人說話一樣**從 LINE 訊息進站到 V1 自我演化終點」的逐步走讀，每步對應到實際 file:line。給接手的人（人類或 agent）一份看完就知道整套怎麼跑。

---

## 情境：OP 同事美鳳在 LINE 群問「12/27 江南還有位嗎」

### 🟢 階段 1：即時處理（V0.2 已 LIVE 2026-05-28）

| # | 動作 | 程式（檔:行） | 為什麼 |
|---|---|---|---|
| 1 | LINE webhook 進站 | `plugins/op-assistant-line/adapter.py` (92KB)<br>systemd unit `hermes-gateway-op-assistant.service` | Hermes 原生 LINE plugin 收 webhook，**已經是 α 路徑**（非 standalone listener） |
| 2 | HMAC 驗章 + parse events | `adapter.verify_line_signature` (adapter.py:245) | 證明訊息真的來自 LINE，非偽造 |
| 3 | 寫 inbound event 到 PG | `adapter._log_inbound_to_kernel` → `closed_loop_kernel.events` 表，`event_type='op_assistant_line_inbound'` | 每則訊息留 trace（2026-05-27 LIVE） |
| 4 | invocation 偵測 | `wannavegtour/line_router.py:262 _detect_invocation()` | 看是 `@小弟` mention 或前綴 `小弟` / `@小弟` / `/小弟` |
| 5 | 不是叫 bot → silent + log，繼續收集對話 | `LineRouter.dispatch()` 回 `DispatchAction.SILENT` | passive listening：群裡不打擾，但 audit 不漏 |
| 6 | 是叫 bot → parser 切意圖 | `wannavegtour/query_parser.py:316 parse_query()`<br>4 intent: `AVAILABILITY_CHECK` / `HISTORICAL_LOOKUP` / `PRICE_EDIT_HINT` / `UNCLEAR` | 純 Python deterministic，**control flow 沒 LLM** |
| 7 | 跳對應 worker | • availability → `availability_checker.py`（查 WC `/products` 名額）<br>• historical → `historical_lookup.py`（查 WC 歷史 / aggregate）<br>• price edit → 直接 refuse（不寫操作）<br>• unclear → ack「我看不懂...」 | Code is Law：每個 intent 對應一個確定函數 |
| 8 | response_formatter 包訊息送 LINE | `response_formatter.py` → LINE Reply API → 失效 fallback Push API | LINE Reply token 1 分鐘免費；過期改 metered Push |
| 9 | 寫 decision log + 可能寫 failure marker | `adapter._write_op_event_logs()` 寫 2 種 event:<br>• `outbound_decision`（每次都寫）<br>• `op_failure_marker`（UNCLEAR / refused 觸發） | 結構化紀錄「bot 怎麼決定的」+「哪些失敗」，對齊 `docs/company-data-contract-v0.md §9` |
| 10 | PII redact | `wannavegtour/redact.py` | user ID / 姓名 etc 寫 audit 前先洗掉 |
| 11 | PG 卡住 → SQLite outbox 緩衝 | `wannavegtour/outbox.py KernelOutbox`<br>檔案 `~/.hermes/run/wannavegtour/outbox.sqlite` | PG 暫時不可用時，先寫本地，PG 復活後 replay 進去（Q4=B no-daemon 設計） |

**對 OP 同事體驗：1 秒看到回應，跟以前一樣。差別在 backend 多了結構化紀錄。**

---

### 🟡 階段 2-3：每日 LLM 整理（鎖板未 ship）

| # | 動作 | 程式 | 為什麼 |
|---|---|---|---|
| 12 | Cron 每 4hr Python 分群 | `scripts/op_assistant_4hr_cluster.py`（**未寫**） | 純 Python deterministic 算頻率、分群，免費，為下一階段 gemma4 鋪料。寫 `4hr_python_summary` event |
| 13 | Cron 每日 09:00 gemma4 找 pattern | v2 doc 已 spec（**未寫**）<br>用 Ollama gemma4:e4b 本地 LLM | 廉價 LLM 看 4hr summary + failure marker，寫人話摘要、抓 pattern。寫 `daily_curation_summary` |
| 14 | 推 Telegram 給 Gary | gemma4 完寫推 skimm3r918_bot | Gary 每天早上看一份「昨天 OP bot 哪些卡住、哪些值得修」 |

**對 Gary 體驗：早上 Telegram 收到「昨天小弟答不出『國內團』8 次，要不要加 keyword？」**

---

### 🔴 階段 4-11：V1 自我演化（設計中，無 code）

| # | 動作 | 程式（規劃） | 為什麼 |
|---|---|---|---|
| 15 | Gary 在 Telegram 按 inline 鍵盤「這個要修」 | telegram-op-control plugin（adapter.py + dispatcher.py 已存在 scaffold） | 寫 `gary_marked_for_fix` event |
| 16 | 達門檻觸發貴 LLM (Codex/Claude) | proposer orchestrator（**未寫**） | isolated git worktree，**allowlist 強制只能改 `wannavegtour/query_parser.py`**（不可改其他檔） |
| 17 | LLM 寫 patch → 寫 `improvement_candidates` row | proposer 看 redacted 資料、不看 raw PII | 一個候選 = 一個 patch |
| 18 | Sandbox 4-metric 驗證 | `closed_loop_kernel/sandbox.py PythonSandbox`（code LIVE，**未對 OP 用過**） | 重 replay 過去 audit log，驗 patch 不退化、不破壞既有 reply |
| 19 | pass → 推 Telegram diff + risk + rollback 計畫 | telegram dispatch（**未寫**） | Gary 看 diff 決定 ✓ / ✗ |
| 20 | ✓ → apply_candidate | `closed_loop_kernel/engine.py:358-430`（code LIVE，**未對 OP 用過**） | 寫 `artifacts` 表 version+1 |
| 21 | Materializer worker 自動實寫 | `scripts/op_assistant_materialize.py`（**未寫**） | isolated worktree → patch → format → test → git commit → push → `systemctl restart` |
| 22 | runtime 自動載新 query_parser.py | service restart 後 import 新版 | OP 同事下次再問同問題就會答 |
| 23 | LLM 退場 — pattern_routes 註冊 | `pattern_routes` 表 schema LIVE，**0 row** | 學到的 keyword 寫進這表，未來 router 先 lookup，不用再經 LLM |

---

## 🏗️ 跨階段元件對照（30 秒看完全貌）

```
🟢 LIVE 的元件
─────────────────────────────────────────
plugins/op-assistant-line/adapter.py        ← Hermes LINE plugin 整合
wannavegtour/line_router.py                 ← invocation 偵測 + 路由
wannavegtour/query_parser.py                ← 4 intent 分類
wannavegtour/availability_checker.py        ← 查 WC 名額
wannavegtour/historical_lookup.py           ← 查 WC 歷史
wannavegtour/response_formatter.py          ← 包 LINE 回覆
wannavegtour/redact.py                      ← PII 洗白
wannavegtour/outbox.py                      ← SQLite 緩衝
closed_loop_kernel/postgres.py              ← schema (events/attempts/failures/candidates/replays/approvals/artifacts/pattern_routes)
closed_loop_kernel/sandbox.py               ← PythonSandbox AST lint (code 在但 OP 還沒用)
closed_loop_kernel/engine.py                ← apply_candidate (code 在但 OP 還沒用)
docs/company-data-contract-v0.md §9         ← Failure Record 公司契約
docs/contracts/op_assistant_event_mapping_v0.md  ← OP scenario → 契約 enum 映射

🟡 設計鎖板、未寫 code
─────────────────────────────────────────
scripts/op_assistant_4hr_cluster.py         ← Stage 2 cron
(daily curation + telegram push)            ← Stage 3 cron
telegram-op-control/adapter.py + dispatcher.py  ← scaffold 已存在，dispatch logic 未完
op_assistant_apply_canary.py                ← 部分寫了（git revert path 已有）
op_assistant_etl.py / daily_curate.py /      ← scripts/op_assistant/ 底下 17 個 script
   sandbox_replay.py / patch_emitter.py /     部分是 spec/部分 scaffold/部分 LIVE
   monthly_maintenance.py 等                  （要逐檔看才知道哪些已 ready）

🔴 V1 完全沒寫
─────────────────────────────────────────
gary_marked_for_fix Telegram handler
proposer orchestrator (Codex/Claude integration)
op_assistant_materialize.py
shadow mode / rollback contract / actor separation
```

---

## 🎯 關鍵理解（給接手的人）

1. **Hermes α 整合已經完成了** — Stage 1 第 1 步用的就是 Hermes 原生 LINE plugin，不是 standalone listener。`docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md` 寫的 standalone listener 是 Mac mini 時期的版本，DGX Spark 上已是 Hermes-native。
2. **V0.2 = 累積資料階段**，現在每筆對話都已經結構化進 PG（Stage 1 step 9）。OP 同事體驗沒變。
3. **V1 = 自動閉環階段**，要寫的是 Stage 12-23 的 cron + LLM + Materializer + Telegram approval。
4. **Code is Law 沒破**：LLM 只在 META 路徑（Stage 13, 16）— 用來觀察 / 提議。OP 回應路徑（Stage 1）全 deterministic Python，沒 LLM 在 control flow。
5. **Sandbox 驗證 + Gary Telegram 簽核** 是 Stage 16-20 的 gate — LLM 提的 patch 沒過這兩關不會落實檔。

---

## 接 task 的人讀完這份之後該幹嘛

按 `docs/plans/INDEX.md` 的 Read-first protocol：

1. `git switch main && git pull --ff-only origin main`
2. Read `AGENTS.md`（工作偏好 + How To Talk With Gary）
3. Read **本檔**（你正在讀）
4. Read `docs/plans/INDEX.md`（active plans 索引）
5. Read `docs/company-data-contract-v0.md §9` + `docs/agent-profile-registry-v0.md`（公司契約）
6. Drill into 跟當前 task 直接相關的 plan：
   - 接 V0.3 (Stage 12-23)：讀 `docs/plans/2026-05-28-op-assistant-v0.3-design.md` (2026-05-29 拍板 canonical)
   - 接 learning loop：讀 `docs/plans/2026-05-28-learning-loop-design-v0.2.md`
   - 接 marketing agent：讀 `docs/plans/2026-05-26-marketing-agent-bootstrap.md`
   - 接 全公司 bot map：讀 `docs/plans/2026-05-26-wannavegtour-full-company-bot-map-v2.md`

---

## Cross-references

- `docs/plans/INDEX.md` — 所有 active plan 索引
- `docs/plans/2026-05-28-system-state-overview.md` — 本檔的 canonical 來源（含 Mermaid 圖）
- `docs/plans/2026-05-28-learning-loop-design-v0.2.md` — learning loop 設計 canonical
- `docs/plans/2026-05-28-op-assistant-v0.3-design.md` — V0.3 設計 canonical (2026-05-29 拍板)
- `docs/plans/2026-05-26-wannavegtour-full-company-bot-map-v2.md` — 全公司 bot map (α/β/γ/δ/ε)
- `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md` — Mac mini → DGX Spark migration 手順
- `docs/handoffs/2026-05-25-wannavegtour-session-context.md` — 5/25 架構討論 session 紀錄
