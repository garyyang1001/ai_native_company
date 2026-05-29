# Round 07 — 4 contracts locked(經 codex 兩輪 review)

**Date**:2026-05-29
**Participants**:Claude ↔ codex `gpt-5.5 xhigh` × 2 輪(`019e7341` + `019e734f`)
**Status**:Round 7 lock complete — 3 contracts + index sign-off ready

---

## 1. 情境

Round 6 collapse 後 Gary mandate 直接動 Round 7「鎖 4 contracts」。我寫 drafts → codex Round 7 給 **4 全 No-Go**(全是真實 bug)→ 我全收逐個修 → codex Round 7.5 二次 review 給 **2 Go + 2 small SQL/wording fixes** → 我修完 → 收斂 lock。

## 2. Codex Round 7(第一輪)4 No-Go

完整 output:`.claude/jobs/1d06a75b/round07_output.md`

| 文件 | codex 抓的問題 | 我的修法 |
|---|---|---|
| README | 「4 contracts」字眼跟實際 3 不符;reviewer separation 寫成「no path writes multiple tables」跟 Phase 4 同 transaction 必寫多表衝突 | 改「3 contracts + index」+ role-based separation(propose/approve/apply 三角色不同人) |
| callback_data | 8 hex prefix 引入 collision/stale 風險省 24 byte 不值得;「全部 KILL」沒 summary id 對應 | 改 32-hex 完整 UUID(`apv:<hex32>`,under 64 byte);加 `killall:<daily_summary_id>` |
| approval_audit | INSERT-then-UPDATE 順序 → UPDATE 失敗留假 approval;append-only + unique 互相矛盾 | 改 `SELECT FOR UPDATE → check → INSERT approval → UPDATE candidate → INSERT event`,全 atomic transaction;選 unique 不選 re-approve |
| sandbox_protocol | `seed = hash(candidate_id)` Python hash 有 process salt 非 deterministic;run id 沒包 model_digest + corpus;Phase 6 需 sandbox DB 但說 Round 13 才建(時程矛盾) | seed 改 `sha256(candidate_id)[:16] as int`;run id 算 `(candidate, seed, digest, corpus_hash, clock_started_at)`;sandbox DB 挪 Round 8 前置 |

## 3. Codex Round 7.5(第二輪)結果

完整 output:`.claude/jobs/1d06a75b/round07_5_output.md`

| 文件 | codex 結論 | 我的修法 |
|---|---|---|
| README | **大致關閉**(Conditional Go)— approval_audit 尾段「No path writes multiple tables」把舊矛盾帶回來 | 把 approval_audit 「Reviewer separation enforcement points」table 重寫成 role-based(Phase 4 dispatcher 明確標可寫 approvals + candidate + events in single transaction) |
| callback_data | ✅ **Go** — 32-hex + killall summary id 都對;小補強:batch KILL 部分成功要 structured 回報 | 加 `killall partial-success reporting` 段,明列 ✅ killed / ⏭ stale / ❌ failed 三個 count |
| approval_audit | **No-Go** — PG partial unique index 跟 `ON CONFLICT (col)` 配不上;reviewer separation 尾段矛盾 | partial unique 改 full unique(NULLS DISTINCT default 讓 V0.2 既有 NULL row 不衝突);reviewer separation 同上一行 |
| sandbox_protocol | **No-Go** — 3 個技術坑:`seed` 16 hex unsigned 超 BIGINT signed 上限 / `corpus_snapshot_hash` 只 hash row id 不 hash payload / 「byte-identical row」跟 `created_at DEFAULT NOW()` 衝突 | seed mask 63-bit(`& ((1<<63)-1)`);corpus_hash 加 anonymised payload digest;byte-identical wording 改成「same id + same metrics,timestamp 不算」 |

## 4. 最終 3 contracts + index 狀態

| 檔 | 狀態 |
|---|---|
| `docs/contracts/op_assistant_v0.3/README.md` | locked — role-based reviewer separation,3 contracts + this index |
| `docs/contracts/op_assistant_v0.3/callback_data_v0.md` | locked — 32-hex UUID format,killall batch UX,parser regex `^(apv\|rej\|vw\|kill\|killall):([0-9a-f]{32})$` |
| `docs/contracts/op_assistant_v0.3/approval_audit_v0.md` | locked — atomic SELECT-FOR-UPDATE-then-INSERT-then-UPDATE-then-EVENT,full unique on source_event_id,role-based separation |
| `docs/contracts/op_assistant_v0.3/sandbox_protocol_v0.md` | locked — sandbox DB at Round 8 first commit,sha256-based deterministic seed/run_id,corpus hash includes payload,metric-scope honesty disclaimer |

## 5. 不再 Round 7.75

Karpathy 2 simplicity:codex Round 7.5 的 4 個 fix 都是 SQL syntax / wording 級別,不是 architectural。我修對的 confidence 高:

- `full unique` vs `partial unique`:PG 文件直接寫 `NULLS DISTINCT` 是 default,多 NULL OK
- `seed mask 63-bit`:PG BIGINT signed 上限 `2^63 - 1`,公式正確
- `corpus_hash includes payload`:重跑可驗證性的補強
- `byte-identical wording`:文字 clarify,不影響 schema

Round 8 真實作時若 contract 還有 issue,patch 並 bump v0 → v0.1。

## 6. Round 8 計畫

Round 8 開工事項:
1. **sandbox DB scaffold**:`docker exec psql -c "CREATE DATABASE op_assistant_sandbox_kernel"` + apply POSTGRES_SCHEMA + sandbox_runs DDL
2. **schema migration**(production)— approvals 表加 5 column + 2 unique index
3. **Phase 6 sandbox replay engine MVP**(`scripts/op_assistant/op_assistant_sandbox_replay.py`)— 4 metric 計算,corpus 取樣,FakeClock,model digest 記錄
4. **Phase 3 inline keyboard sender**(`op_assistant_daily_curate.py` 加 `_render_inline_keyboard`)— 用 callback_data v0 spec

兩條平行線(Phase 3 ↔ Phase 6)依 Round 6 ship 序列。

## 7. Karpathy lens

- **#1 Think Before Coding**:Round 7 收 4 全 No-Go 沒辯護,silently 假設都 surface
- **#2 Simplicity First**:Round 7.5 後決定停 iteration,不無限 ping-pong
- **#3 Surgical Changes**:每次 patch contracts 只 Edit 對應段,沒整檔重寫
- **#4 Goal-Driven Execution**:Round 7 success criteria = 3 contracts + index canonical lock,4 個 codex Round 7 No-Go + 4 個 codex Round 7.5 fixes 全 close

## 8. Artifacts

- Round 7 prompt:`.claude/jobs/1d06a75b/round07_prompt.md`(512 行)
- Round 7 codex output:`.claude/jobs/1d06a75b/round07_output.md`(4 No-Go)
- Round 7.5 prompt:`.claude/jobs/1d06a75b/round07_5_prompt.md`(647 行,含修補後 4 檔)
- Round 7.5 codex output:`.claude/jobs/1d06a75b/round07_5_output.md`(2 Go + 2 small fix)
- 3 contracts + 1 index in `docs/contracts/op_assistant_v0.3/`
