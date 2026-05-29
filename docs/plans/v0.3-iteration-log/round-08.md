# Round 08 — Phase 6 sandbox replay + Phase 3 inline keyboard + schema scaffold

**Date**:2026-05-29
**Status**:Round 8 lab-lane + human-review-lane plumbing landed; Phase 4/5/7/8 to come
**Commits**:`6c41f42` schema, `fb0eb1f` Phase 6 replay, `<this>` Phase 3 keyboard + log

---

## 1. 情境

Round 7 鎖了三個 contracts(callback_data / approval_audit / sandbox_protocol)。Round 8 把 contracts 對應的程式落下去 — 兩條平行 ship 線(實驗室線 Phase 6 + 人類審核線 Phase 3)同 round 收。

順序按 contracts 對應 schema → engine → UI。Phase 4 dispatcher 留下一輪(它接 Telegram callback,但本輪先把推按鈕做好,讓 Round 9 有東西可解析)。

## 2. Round 8 step-by-step 戰報

### Step 1 — sandbox DB scaffold + production schema migration(commit `6c41f42`)

- `docker exec psql -c "CREATE DATABASE op_assistant_sandbox_kernel"` 建立 sibling DB in 同 container
- `closed_loop_kernel/postgres.py` 加 14 行 idempotent ALTER + `sandbox_runs` CREATE TABLE:
  - production approvals 表加 4 NULL-able column(approval_channel / source_event_id / channel_message_id / reject_reason)
  - decision CHECK 擴含 'killed'
  - full UNIQUE on source_event_id(NULL DISTINCT 讓 V0.2 legacy row 並存)
  - partial UNIQUE on (candidate_id) WHERE decision IN ('approved','rejected')
  - sandbox_runs 表 13 column 含 corpus_snapshot_hash(Round 7.5 codex catch)
- `KernelStore.from_url(...).initialize()` 兩 DB 跑通 — idempotent

verify: 兩個 DB `\dt` 都列 sandbox_runs + 4 個 approvals 新 column + 兩個 unique index ✅

### Step 2 — Phase 6 sandbox replay engine MVP(commit `fb0eb1f`)

`scripts/op_assistant/op_assistant_sandbox_replay.py`(497 行)+ tests(376 行)

實作要點:
- `compute_seed(candidate_id)` = sha256 前 16 hex,mask 63-bit fits PG BIGINT(Round 7.5 fix)
- `compute_run_id(candidate, seed, model_digest, corpus_snapshot_hash, clock_started_at)` — 5 input 都影響 id
- `compute_corpus_snapshot_hash` 包 row id + anonymised payload(Round 7.5 fix)
- `FakeClock` 注入,production wall-clock 不污染
- `load_query_parser` 用 `importlib.util.spec_from_file_location` + `sys.modules` register(否則 `@dataclass(frozen=True)` introspect 失敗)
- `_ParserHandle` wrapper — regex extras 不 append 到 `_DATE_PATTERNS`(那預期 2 group),改 wrap 原 parser,unclear 時再試 regex,match 就 substitute intent。V0.2 `query_parser.py` source 完全沒動。
- 4 metric 計算:regression(success → success)/ improvement(failure → ok)/ ambiguity(V0.3 placeholder = 0)/ over_greedy_rate(unclear 命中比例)
- `ON CONFLICT (id) DO NOTHING` 跑 ON sandbox_runs INSERT — 同 input 同 run_id idempotent

production verify(2026-05-29):
- Candidate 3f356f63「沒有賣完」keyword → passed(0 regression / 1 improvement / 7.14% over-greedy)
- Candidate 1299448b「有哪些團.*?沒有賣完」regex → passed(wrapper 處理 regex,沒 break date 解析)
- 同 `--clock-anchor 2026-05-29T09:00:00+00:00` 兩次,run_id 一致,sandbox_runs row 不重複 ✅

tests:27 個全 pass — 涵蓋 seed determinism + BIGINT fit / corpus hash 對 payload drift 敏感 / run id 5 input 全敏感 / FakeClock tick / 4 metric 每條 fail 條件 / parser isolation / wrapper regex behaviour / extras kind whitelist

### Step 3 — Phase 3 inline keyboard sender(本 commit)

`scripts/op_assistant/op_assistant_daily_curate.py` 改:
- `_persist_candidates` 多回 `candidates` field(list of `{id, label_index, proposal_type, value}`)讓 sender 拿得到順序
- 新 `_render_inline_keyboard(candidates)`:每個 candidate 一 row 三 button(✅ 批准 / ❌ 拒絕 / 🔍 看 sandbox),callback_data 用 contract 規範的 `<action>:<candidate_uuid_hex32>` 形式
- `_push_telegram` 加 `candidates` 參數,env `OP_PHASE3_INLINE_KEYBOARD=1` gate keyboard 開關
- Phase 4 dispatcher 還沒寫,所以**預設關 keyboard**;Phase 4 ship 後再 set env

tests:`tests/test_op_assistant_phase3_keyboard.py` 7 pass — keyboard structure / callback_data 對 contract regex / 32-hex 去 dash 小寫 / label_index 從 1 開始 / Phase 3 不含 KILL button / `_persist_candidates` candidates field 結構

Phase 2 既有 6 tests 因 `_persist_candidates` 加 candidates field 失效 → sed 改 exact-dict 比對成 separate field assertion(no semantic 變動)

### Step 4 — round-08.md(本 commit)

## 3. Round 8 全部統計

| 項目 | 數字 |
|---|---|
| commits 進 main | 3 (schema / Phase 6 / Phase 3) |
| 新 code 行數 | ~1200(含 tests) |
| tests pass total | 45(11 phase2 + 7 phase3 + 27 sandbox replay) |
| production sandbox_runs row | 3(兩 candidate × 不同 clock anchor) |
| schema migration applied | 2 DB(production + sandbox) |

## 4. 剩下待做(Round 9+)

| Round | 目標 |
|---|---|
| 9 | Phase 4 dispatcher(`plugins/telegram-op-control/dispatcher.py`)— 接 Telegram callback,parse callback_data,跑 `claim_and_apply` 三層 atomic transaction |
| 10 | Phase 5 audit chain(`approvals` 寫入 + `events.candidate_status_changed`)— 跟 Phase 4 一起 commit 也行,或分輪 |
| 11 | Phase 7 patch emitter + AST guard(`scripts/op_assistant/op_assistant_patch_emitter.py`) |
| 12 | Phase 8 canary deploy + KILL switch(`scripts/op_assistant/op_assistant_canary_judge.py`) |
| 13 | sandbox 1000-case seed + expander |
| 14 | 真跑 1000 case + 量 5 完美 KPI |
| 15 | 4 DB self-maintenance scripts |

## 5. Phase 4 啟動條件

Round 9 開工前 ready check:
- ✅ Phase 3 已寫好 inline keyboard sender(Round 8 step 3)
- ✅ approvals schema 有 source_event_id + channel_message_id + reject_reason 三欄
- ✅ telegram-op-control plugin(Phase 1)已 ship,events.telegram_inbound 接收 Telegram callback_query
- ✅ callback_data contract 鎖了(Round 7)
- ⚠️ env `OP_PHASE3_INLINE_KEYBOARD=1` 還沒開 — Round 9 Phase 4 寫好後再開

## 6. Karpathy lens

- **#1 Think Before Coding**:wrapper 模式繞開 `_DATE_PATTERNS` 修改是 think 出來的(原 V0.3 doc 寫「append 進 _DATE_PATTERNS 或自訂 list」沒明 spec,實作時 silently 假設 append 進 _DATE_PATTERNS,跑 regex candidate 才 surface 錯誤)
- **#2 Simplicity First**:Phase 3 用 env gate 不開 keyboard 預設,避免 Phase 4 沒 ship 期間 Gary 按按鈕 hang
- **#3 Surgical Changes**:`query_parser.py` V0.2 source 完全沒動(wrapper 在 sandbox 內部處理 regex extras)
- **#4 Goal-Driven Execution**:Round 8 success criteria — Phase 6 真實 production candidate 跑通 ✅ / Phase 3 keyboard JSON 結構對 contract regex ✅ / 兩 DB schema clean ✅

## 7. Artifacts

- Round 8 step 1-3 三個 commit on main
- production op_assistant_kernel.sandbox_runs 3 row
- production op_assistant_sandbox_kernel — clean sibling DB ready for Round 13 1000-case sim
- 既有 Phase 1+2 code 100% backward-compatible(Phase 2 既有 tests 改成 separate field assertion,語意不變)
