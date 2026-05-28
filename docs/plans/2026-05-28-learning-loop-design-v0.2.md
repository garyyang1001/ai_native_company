# OP Bot Learning Loop Design v0.2

**Status**:草案,待 Gary review
**日期**:2026-05-28
**作者**:Claude + Codex session `019e6576-53de-7ac0-8b33-749dafd9958c`(基於 Gary 2026-05-27 口述 mental model + Karpathy 4 原則套用)
**Supersedes**:`docs/plans/2026-05-27-learning-loop-design-v0.md`(v0.1)

---

## 為什麼有 v0.2

v0.1 鎖定 Q1-Q4 後,Gary 2026-05-28 裝了 `karpathy-guidelines` skill,要求對 v0.1 跑一次 Karpathy 4 原則自我審查。Codex 審查發現 Q1/Q3/Q4 都有 hidden assumption 或 over-engineering。Gary 重新鎖定:

| Question | v0.1 lock | v0.2 lock | 影響 |
|---|---|---|---|
| Q1 寫入位置 | events 表 + 自創 event_type | **`failures` 表 + contract §9 enum + `domain_failure_code` 子欄位** | 從 OP-only 升 cross-dept contract alignment |
| Q3 ID 模型 | 只用 `inbound_event_id` | **三層**:`task_id` + `run_id` + `inbound_event_id` | follow-up detection 可掛回 |
| Q4 outbox | SQLite outbox + daemon | **SQLite outbox,只做 enqueue + flush_once + idempotency,不 daemon** | Karpathy Simplicity First |

Q2(`wannavegtour/redact.py` 獨立 module)沒變。

**重要轉向**:Q1=B 等於 OP 從第一天就吃 `docs/company-data-contract-v0.md` §9 Failure Record contract。**不是「OP only」了,是「OP 是公司契約落地的第一個 case study」**。

---

## v0.2 鎖定的設計(以契約為準)

### 缺塊 1 重寫 — 失敗紀錄員 + 決策日誌(對齊 contract §9)

#### 寫入點

`plugins/op-assistant-line/adapter.py:1059-1135` routing 完成後加 hook。

#### 流程(每筆 LINE 訊息)

```
1. LINE webhook → adapter._handle_message_event(event_obj)
2. adapter._log_inbound_to_kernel(...) 寫 events table (existing,已實作)
3. LineRouter.dispatch(wc_event) → result
4. adapter 送 reply (existing,已實作)
5. 【新增】adapter._write_decision_log(...) → 寫 events table (event_type='outbound_decision')
6. 【新增】if trigger_hit: adapter._write_failure(...) → 寫 failures table (contract §9 schema)
7. 【新增】DB 失敗 → enqueue 到 SQLite outbox (next message flush_once)
```

#### Decision Log schema(寫 events 表)

`event_type = 'outbound_decision'`,payload JSONB 結構:

```json
{
  "task_id": "task_<uuid>",
  "run_id": "run_<uuid>",
  "inbound_event_id": "evt_<uuid5(message_id)>",
  "profile_id": "op-assistant-line",
  "parser_result": {
    "intent": "availability_check | historical_lookup | price_edit_hint | help_request | unclear",
    "confidence": 0.0,
    "matched_rule": "...",
    "extras": {...}
  },
  "router_action": "REPLY | SILENT",
  "reply_kind": "availability_result | historical_result | help_text | unclear_ack | refusal | none",
  "reply_hash": "<sha256 of reply text>",
  "reply_preview_redacted": "...",
  "message_hash": "<sha256 of inbound text>",
  "message_preview_redacted": "...",
  "user_hash": "<sha256 of LINE user_id>",
  "conversation_hash": "<sha256 of group/room_id>",
  "code_version": "<git sha>",
  "ts": "ISO 8601"
}
```

#### Failure Record schema(寫 `failures` 表,contract §9.4)

對齊 `closed_loop_kernel/postgres.py:138-145` 的 `failures` schema:

```sql
INSERT INTO failures (
  id, attempt_id, failure_type, context, status, created_at
) VALUES (
  gen_random_uuid(),
  <attempt_id>,             -- 對應到 attempts row(下面解釋)
  <one of contract §9.1 enum>,
  jsonb,
  'open',
  NOW()
)
```

##### `failure_type` 必須是 contract §9.1 的 7 個之一

```text
hard_failure              ← 任務失敗、API error、timeout、例外
contract_violation        ← 沒照 Agent Output Envelope 交付
verification_failure      ← sandbox / test / schema check 沒過
human_rejection           ← Gary 或 OP 同事明確退回
quality_regression        ← 新版 agent 比舊版表現差
stale_or_dirty_memory     ← agent 引用過期 / 重複 / 廢棄資料
outcome_failure           ← 任務表面完成但後續證明沒效果
```

OP bot 常見映射:
- 美鳳問「國內團」bot 回 ack → `outcome_failure`(表面回了但沒解決)
- bot 回錯方向,美鳳糾正「我問國內」→ `human_rejection`
- bot 該回卻沒回(SILENT but should REPLY)→ `quality_regression`
- parser 拋例外 → `hard_failure`

##### `context` JSONB 子欄位(OP-specific 細節放這)

```json
{
  "task_id": "task_<uuid>",
  "run_id": "run_<uuid>",
  "inbound_event_id": "evt_<uuid5>",
  "profile_id": "op-assistant-line",
  "domain_failure_code": "<OP-specific 字串>",
  "trigger_reason": "<為什麼我們知道這是 failure>",
  "evidence_json": {...},
  "replay_input_json": {...},
  "parser_result": {...},
  "router_action": "...",
  "reply_kind": "...",
  "message_hash": "...",
  "user_hash": "...",
  "code_version": "..."
}
```

##### `domain_failure_code` 字串約定(OP-only,可擴充)

```text
missed_actionable_intent       ← parser 回 unclear 但訊息有明確 intent
reply_mismatch                 ← bot 有回但跟 OP 期望不符
false_positive_reply           ← bot 不該回卻回
unexpected_silent              ← 該回卻沒回
```

不准進 canonical `failure_type` 欄位。

##### `trigger_reason` 字串約定

```text
parser_returned_unclear        ← parser 自報 UNCLEAR
fallback_reply_sent            ← adapter 走 Hermes agent fallback
negative_followup_pattern      ← 下一條訊息有「不是」「我問的是」等糾正詞
gary_marked_bad                ← Gary 在 Telegram 標
manual_review                  ← 人工 audit 後補登
```

#### Attempt 怎麼處理

contract §6 規定 Agent Output Envelope,有 `attempt_id` 概念。`closed_loop_kernel/postgres.py` 也有 `attempts` 表。

v0.2 first iteration:**每次 LINE 訊息 handling 寫一筆 `attempts`**,然後 `failures.attempt_id` 引用它。具體欄位之後再對齊 contract §6,first iteration 先用 attempts 表既有最小欄位。

(open question:attempts schema 跟 contract §6 是否需要 reconcile?留 v1 處理)

---

### 缺塊 2 — Candidate Proposer(沒變,carry-over 自 v0.1)

兩層架構,不變:
- **廉價研究員(每 4 hr Python + 每 24 hr gemma4)** — 分類、找 pattern,不寫 patch
- **貴的 code writer(觸發才跑)** — Codex CLI / Claude,在 isolated git worktree 寫 patch,只允許改 `wannavegtour/query_parser.py` 或更窄

`target_path_allowlist` 強制(schema 或 materializer 驗,不只文件)。

PII redaction 在 proposer 讀資料前完成 — proposer 看 redacted view,不讀 raw text。

---

### 缺塊 3 — Materializer(沒變,carry-over 自 v0.1)

Outbox pattern:apply_candidate 只更新 DB,materializer worker 監聽 `candidate_applied` event,在 isolated worktree 套 patch → format → replay → git commit + push → restart service。失敗 → `materialization_failed`。

---

### 缺塊 4 — Runtime SoT(沒變,carry-over 自 v0.1)

Runtime 永遠以 systemctl restart 後重新 import 為準。Materializer push 完之後 production-critical patch 順手 `systemctl --user restart hermes-gateway-op-assistant.service`。

---

## Karpathy verify checks(套 Codex 件 3 審查,每步具體)

(以下 8 步從 v0.1 carry-over,但每步加 verify check)

### Step 1:寫 `wannavegtour/redact.py` + `tests/test_redact.py`

**做什麼**:約 30 行 module,提供 `redact_text(s) -> (preview, hash)` / `hash_user_id(uid)` / `hash_message(s)`。

**Verify**:
```python
preview, h = redact_text("明天 18:00 美鳳訂位 0912345678")
# preview 不包含 "0912345678"
# preview 包含穩定 hash token (e.g. "[phone:...]")
# h 是 sha256 of original
```

```bash
python3 -m unittest tests/test_redact.py
```

### Step 2:寫 `wannavegtour/outbox.py` + `tests/test_outbox.py`

**做什麼**:約 80 行,純 SQLite operations。Functions:`enqueue(record) -> outbox_id` / `flush_once(writer_callable) -> (success_count, fail_count)` / `mark_acked(outbox_id, kernel_ack_id)`. **不 daemon**。

**Verify**:
```python
# 1. temp SQLite 建表成功
# 2. 同一 idempotency_key enqueue 兩次只留一筆
# 3. flush_once(fake_writer_success) → row status = 'acked'
# 4. flush_once(fake_writer_failure) → row status 仍 pending,attempt_count += 1,last_error 有值
```

```bash
python3 -m unittest tests/test_outbox.py
```

### Step 3:寫 OP event mapping doc(**不叫 contract**)

**做什麼**:`docs/contracts/op_assistant_event_mapping_v0.md`(注意:**mapping** 不是 contract,避免變方言)。內容:
- 明文引用 `docs/company-data-contract-v0.md` §4-9
- `event_type='outbound_decision'` payload schema(上面 decision log section)
- `failures.context` JSONB 子欄位約定(上面 failure section)
- `domain_failure_code` enum
- `trigger_reason` enum
- 任何 contract enum 怎麼映射到 OP 場景的範例(e.g. 美鳳糾正 → `human_rejection`)

**Verify**:
- 文件明確 link 到 contract §9
- 沒有把 OP-specific 字串放進 canonical `failure_type` 欄位
- `docs/plans/INDEX.md` 已更新加 mapping doc

```bash
git diff -- docs/contracts docs/plans/INDEX.md
grep -E "failure_type.*missed_actionable_intent" docs/contracts/op_assistant_event_mapping_v0.md
# 預期:沒結果(只在 domain_failure_code 出現)
```

### Step 4:改 `plugins/op-assistant-line/adapter.py:1059-1135` 加 hook

**做什麼**:routing 後加 4 個函式 call(decision write、可能的 failure write、outbox enqueue on failure)。

**Surgical 邊界**(嚴格遵守):
- ✅ 允許:capture inbound_event_id / task_id / run_id;dispatch 後寫 decision;trigger 命中寫 failure;DB 失敗走 outbox;catch + warn 不擋 reply
- ❌ 禁止:動 `LineRouter.dispatch()`;改 parser 規則;改 reply 文案;改 Hermes fallback;順手清 audit JSONL;改 systemd unit

**Verify**(用 mocked DB/router):
```python
# normal REPLY → decision written, no failure
# fallback reply → decision + failure (failure_type='outcome_failure', trigger='fallback_reply_sent')
# SILENT with no trigger → only decision
# DB exception → outbox enqueued, LINE reply unaffected
```

不接受「看起來可以」。要有 unit test 或 smoke harness 跑過。

### Step 5:本地 smoke test

**Verify**:
- 發一筆測試 inbound
- psql query op-assistant-kernel:`SELECT id, event_type FROM events WHERE event_type='outbound_decision' ORDER BY created_at DESC LIMIT 1` 看到剛寫的 row
- failure trigger case → `SELECT id, failure_type, context FROM failures ORDER BY created_at DESC LIMIT 1` 看到
- redacted preview 不含 phone / raw LINE id
- 關掉 op-assistant-kernel 容器 → 重發訊息 → SQLite outbox 有 pending row(`sqlite3 ~/.hermes/run/wannavegtour/outbox.sqlite "SELECT count(*) FROM kernel_outbox WHERE status='pending'"`)

### Step 6:`systemctl --user restart hermes-gateway-op-assistant.service`

**Verify**:
```bash
systemctl --user is-active hermes-gateway-op-assistant.service
journalctl --user -u hermes-gateway-op-assistant.service -n 100
```
必須:
- service active
- 無 import error
- 無 DB loop error
- 測試 LINE 訊息仍有原本 reply 行為

### Step 7:跑一週累積 row

每天看(Gary 從 Telegram 摘要 or psql):
- decision count(分母)
- failure count by contract `failure_type`
- 來自 `domain_failure_code` 的 OP top 10
- outbox pending count
- 抽樣 5 筆 row 確認 redaction 工作(不含 phone / raw user id)

**停止條件**:outbox pending 持續上升 → 停,不要進缺塊 2(candidate proposer)。

### Step 8:用資料 inform 缺塊 2 設計

**Verify**:
- 至少 10 筆同類 failure 或 Gary 明確標
- 有 before/after replay input(從 `evidence_json` / `replay_input_json` 抽)
- candidate proposer 只指向 allowlist path
- 沒有 raw text 進 proposer prompt
- 還沒做 materializer 前,**不准改 production source**

---

## 9 hole 處置(carry-over 自 v0.1,可能微調)

### ✅ v0.2 已吸收

- **#1 ground truth** — via `trigger_reason='gary_marked_bad'` / `manual_review` / `negative_followup_pattern`
- **#2 outbound decision log** — `event_type='outbound_decision'` 每筆都寫
- **#8 PII 最小化** — 不存 raw text,只存 hash + redacted_preview;`redact.py` 是 helper,但讀-time view 之後也要做
- **新增 correlation id** — task_id + run_id + inbound_event_id 三層串
- **#4 sandbox allowlist 升級** — candidate `target_path_allowlist` 強制

### ⏸️ 在第一次自動 materialize production patch 前必須補

- **#5 shadow mode** — Codex 強調時機:不是 v0 跑完才補,是 materializer 開工前必須有
- **#6 rollback contract** — failure writer 不需要,但 materializer 改 production source 前必須有 git sha / artifact version / revert path

### ⏸️ 可暫緩(P2)

- **#3 SILENT/REPLY action space** — OP bot 先修分類準確度,夠用
- **#7 alert fatigue** — 流量低,先不做 batching / ranking

### 🔧 schema / engine 變更

- **#9 actor separation** — FK / trigger / engine-level validation,確保 proposer ≠ reviewer ≠ approver ≠ materializer 同一 profile。在 candidate apply 前必須補。

---

## 開放問題(待 Gary 對齊或之後決定)

1. **`attempts` schema 跟 contract §6 Agent Output Envelope 怎麼 reconcile?** — first iteration 用 attempts 表既有欄位,v1 再對齊。
2. **`task_id` 開新 task 的精確規則** — 同 user/room + TTL 30-60 分鐘 + 看起來糾正/補充/追問 → 同 task。實作時要寫 `should_continue_task()` 函式。
3. **`domain_failure_code` 字串可擴充嗎?** — 首版 4 個,實際資料可能會出現新類型。要不要由 Gary 標時動態加,還是只允許這 4 個 + `other`?
4. **`negative_followup_pattern` detector 用什麼判**? — 暫時用 keyword list(「不是」/「我問」/「沒回到」等)。要不要更聰明?LLM 判太貴。
5. **`closed_loop_kernel.events` JSONB 之後 query 效率** — 假設 v0 階段資料量低 OK,但要不要先加 GIN index 在 payload?暫不加。
6. **service restart 時機** — Step 6 重啟,但 LINE 訊息正在進來會掉嗎?Hermes 有 graceful shutdown 嗎?**這條 Codex 件 1 hidden assumption 提過,要驗**。

---

## Acceptance criteria(本文件 v0.2 → v1)

- [x] Q1=B 鎖定(failures 表 + contract §9 enum + domain_failure_code 子欄位)
- [x] Q3=B 鎖定(三層 ID:task_id + run_id + inbound_event_id)
- [x] Q4=B 鎖定(SQLite outbox enqueue + flush_once,no daemon)
- [x] Q2 鎖定(`wannavegtour/redact.py` 獨立 module)
- [x] 每步 Karpathy verify check 寫出來
- [x] Surgical 邊界明文(Step 4 允許 / 禁止 list)
- [ ] 上面 6 個開放問題逐項與 Gary 對齊
- [ ] `attempts` schema 跟 contract §6 reconcile 路徑決定
- [ ] Materializer 開工前補 shadow mode + rollback contract + actor separation(schema 變更)

---

## Cross-references

- `docs/plans/2026-05-27-learning-loop-design-v0.md` — v0.1(本 doc supersede)
- `docs/plans/2026-05-26-op-kernel-db-operations-v2.md` — v2.1 canonical OP kernel DB ops
- `docs/company-data-contract-v0.md` §4-9 — L1 資料契約 + Failure Record schema
- `docs/agent-profile-registry-v0.md` + `data/agent-profile-registry-v0.json` — L2 profile 註冊(op-assistant-line 待登)
- `closed_loop_kernel/postgres.py:31-209` — 實作 schema(events / attempts / failures / candidates / replays / approvals / artifacts / pattern_routes)
- `closed_loop_kernel/engine.py:358-430` — apply_candidate(含 race condition check)
- `closed_loop_kernel/sandbox.py:139-153` — PythonSandbox AST lint
- `spec/code-is-law-v0.md` §3 — patch_type 三類
- `wannavegtour/query_parser.py` — 目前 Python 判斷邏輯
- `wannavegtour/line_router.py` — DispatchAction enum
- `plugins/op-assistant-line/adapter.py:1059-1135` — B1 redesign(Python-first routing)
- `AGENTS.md` — Gary 工作偏好 + Doc Discovery Protocol + Karpathy Behavioral Guidelines
- Codex consult session: `019e6576-53de-7ac0-8b33-749dafd9958c`
