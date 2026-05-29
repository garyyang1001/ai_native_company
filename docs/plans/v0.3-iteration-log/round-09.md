# Round 09 — Phase 4 dispatcher + Phase 5 audit chain + Phase 6 trigger

**Date**:2026-05-29
**Status**:Round 9 closed the human-review lane(Phase 3 + 4 + 5)— Telegram button → atomic claim → sandbox replay trigger → reply
**Commits**:`<this>`

---

## 1. 情境

Round 8 把 sandbox DB / Phase 6 replay engine / Phase 3 inline keyboard 蓋好了,但按鈕沒接到任何人 — `OP_PHASE3_INLINE_KEYBOARD` env 預設 off。Round 9 把整條人類審核線打通:Gary 按按鈕 → Telegram 送 callback_query → Phase 1 webhook 落 events → Phase 4 dispatcher 跑 atomic claim → Phase 6 sandbox replay 自動跑 → Phase 5 audit chain 完整紀錄 → Telegram 回 Gary 結果。

Phase 4 跟 Phase 5 在 V0.3 contract 設計上其實是同一段(approval_audit_v0.md 把 dispatcher 跟 audit transaction 寫在一起)— Round 9 一起 ship。

## 2. 新檔

### `plugins/telegram-op-control/dispatcher.py`

- `parse_callback_data(s)` → `(action, target_id_hex32) | None`,嚴格走 contract callback_data_v0.md 的兩條 regex:`^(apv|rej|vw|kill):[0-9a-f]{32}$` 跟 `^killall:[0-9a-f]{32}$`。沒匹配 = `None`,**沒有 LLM fuzzy match**(Code is Rule)。
- `hex32_to_uuid(hex32)` 把 32 hex 回填 dashes → PG UUID 字串。
- `claim_and_apply(store, ...)` 三步驟 atomic transaction(approval_audit_v0.md 完整實現):
  1. `SELECT status FROM improvement_candidates WHERE id = ? FOR UPDATE` 鎖 candidate row
  2. 檢查 `status == expected_from`(`apv/rej` 要 `draft`;`kill` 要 `applied`)。不對 → 寫 `events.telegram_callback_stale` 然後 return `STALE`,**不寫 approvals row**
  3. `INSERT INTO approvals ... ON CONFLICT (source_event_id) DO NOTHING RETURNING id` 防 dispatcher restart 雙寫;沒拿到 row = `ALREADY_CLAIMED`
  4. `UPDATE improvement_candidates SET status = ?` + `INSERT events.candidate_status_changed`,全在同 transaction
- `trigger_sandbox_replay(store, kernel_url, candidate_id)` Phase 4 → Phase 6 銜接:`importlib` 載 `op_assistant_sandbox_replay.run_sandbox_replay` 跑;結果 `passed/failed` 對應 candidate status `sandbox_verified/sandbox_failed`;同 transaction 再寫一筆 `candidate_status_changed` event。
- `render_reply(action, claim, store, candidate_id)` 給 Gary 的白話回覆,符合 AGENTS.md 規則(情境 + 流程 + 下一步)。Reject UX 跟 kill UX 都明列「接下來會發生什麼」,呼應 codex Round 6 的「Reject 不能只回 rejected」要求。
- `dispatch_callback(...)` 整合入口:parse → action 分流 → 回 `{action, claim, reply_text, sandbox_followup?}`。Vw 是 read-only 不打 transaction;kill / killall 暫回「Phase 8 才開」並落 `telegram_callback_unsupported` event。

### `plugins/telegram-op-control/adapter.py` 改動

Phase 1 webhook handler happy path 接出 dispatch hook:

- 拿 `_audit` 回傳的 inbound_event_id(Phase 1 EventWriter.write 本來就 return uuid)
- `if kind == "callback_query"`:`asyncio.create_task(_run_dispatcher(...))` 在 background 跑
- `_run_dispatcher` 走 `asyncio.to_thread` 包同步 dispatcher,跑完 sendMessage Telegram(`/sendMessage` + `/answerCallbackQuery`)
- 任何 dispatcher exception 落 `events.dispatcher_error`,不會把 webhook server 拖垮

Karpathy 3 surgical:Phase 1 既有 44 tests 全綠(我只在 happy path 加 background task + 拿 inbound_event_id;原 audit + dedupe 行為不變)。

### `plugins/telegram-op-control/tests/test_dispatcher.py`(21 tests)

- `ParseCallbackDataTests` × 10:每個 action / 8-hex 拒絕 / 大寫拒絕 / 未知 action 拒絕 / 缺 colon / non-string
- `Hex32ToUuidTests` × 2
- `ClaimAndApplyTests` × 6:happy approve / happy reject / unknown candidate / stale / already_claimed / kill 要求 applied
- `DispatchCallbackIntegrationTests` × 3:apv 流程(寫 approval + 觸發 sandbox + reply 含 ✅)/ malformed callback 不 mutate 只 audit / kill 回 Phase 8 訊息

## 3. Production smoke test(2026-05-29)

對 production op_assistant_kernel 用 `vw` action(唯一 read-only safe)跑:

```python
dispatch_callback(
    store=KernelStore.from_url(prod_url),
    kernel_url=prod_url,
    source_event_id=str(uuid.uuid4()),
    callback_query={
        "data": "vw:3f356f631a3e539b9478a59dcb476611",  # 沒有賣完 keyword
        "from": {"id": 999}, "message": {"chat": {"id": 123}},
    },
)
```

回 result:

```
{
  "action": "vw",
  "claim": null,
  "reply_text": "🔬 sandbox 通過 (關鍵字「沒有賣完」)
                 • 舊規則沒打壞: 0
                 • 新救回失敗: 1
                 • 過去 30 天 unclear 命中率: 7.1%"
}
```

→ dispatcher 真的能在 production 跑 + 讀 candidate `typed_payload` + 讀 sandbox_runs metrics + 拼出 Gary 看得懂的白話回覆。

## 4. 完整人類審核線 wire-up 狀態

| step | who writes | 狀態 |
|---|---|---|
| Gary 看到的 daily 09:00 推播(含 inline_keyboard) | `op_assistant_daily_curate.py` `_render_inline_keyboard` | Round 8 ✅(gated by `OP_PHASE3_INLINE_KEYBOARD=1`) |
| Gary 按按鈕 → Telegram POST callback_query | Telegram itself | — |
| Webhook 落 `events.telegram_inbound` | `telegram-op-control/adapter.py` Phase 1 | Round 9 ✅ unchanged |
| `asyncio.create_task` 拉起 dispatcher | `adapter.py` happy path 末端 | Round 9 ✅ new |
| Parse callback_data | `dispatcher.parse_callback_data` | Round 9 ✅ |
| Atomic claim_and_apply(approvals + candidate + event) | `dispatcher.claim_and_apply` | Round 9 ✅ |
| Trigger sandbox replay(若 apv) | `dispatcher.trigger_sandbox_replay` | Round 9 ✅ |
| Update candidate → sandbox_verified / sandbox_failed | `dispatcher.trigger_sandbox_replay` 內第 2 transaction | Round 9 ✅ |
| Telegram sendMessage + answerCallbackQuery | `adapter._send_telegram_reply` | Round 9 ✅ |

按鈕還沒真開(env flag 預設 off)— Round 10 Phase 7 寫好 patch emitter 之前 keyboard 開了也只會跑到 sandbox_verified 停住。Round 11 Phase 8 ship 後再開,bot 真的會學會新詞。

## 5. 完整 tests 統計

| file | tests |
|---|---|
| Phase 1 adapter(既有) | 44 |
| Phase 2 candidates(Round 8 修) | 11 |
| Phase 3 keyboard(Round 8) | 7 |
| Phase 6 sandbox_replay(Round 8) | 27 |
| Phase 4 dispatcher(Round 9) | 21 |
| **total** | **110** |

全綠。

## 6. Round 10 開工

- Phase 7 patch emitter + AST guard(`scripts/op_assistant/op_assistant_patch_emitter.py`)
- 對 `sandbox_verified` candidate emit git commit:`_AVAILABILITY_KEYWORDS = (..., "新詞")` append
- AST guard 用 `ast.parse` 比 module-level tuple/list literal,改 control flow 即 reject + status='patch_too_invasive'
- 之後 Round 11 Phase 8 canary + KILL,Round 12 sandbox seed,Round 13 真跑 1000 case,Round 14 cleanup scripts,Round 15 KPI 量

## 7. Karpathy lens

- **#1 Think Before Coding**:Round 9 開始我 silently 假設 `_persist_candidates` 已 expose candidates field,Round 8 step 3 才補；提早 think 避免後續又一輪 fix
- **#2 Simplicity First**:dispatcher 用 `asyncio.to_thread` 包既有 sync claim_and_apply,沒重寫成 async;sandbox 觸發直接 inline 不上 queue
- **#3 Surgical Changes**:Phase 1 adapter 只動 happy path 末段(+ background task call),原 44 tests 100% pass
- **#4 Goal-Driven Execution**:Round 9 success criteria — 21 unit tests + production `vw` smoke test 真讀到 metrics ✅

## 8. Artifacts

- `plugins/telegram-op-control/dispatcher.py`(~400 行)
- `plugins/telegram-op-control/adapter.py` 改動(~90 行 net)
- `plugins/telegram-op-control/tests/test_dispatcher.py`(~370 行)
