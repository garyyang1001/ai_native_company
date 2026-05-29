# Round 04 — Phase 2 simple 版 brief + codex conditional GO

**Date**:2026-05-29
**Participants**:Claude ↔ codex `gpt-5.5 xhigh`
**Round 4 status**:codex conditional GO,接 Round 5 實作

---

## 1. 情境

Gary 2026-05-29 拍板「5-6 同事用,不需要大企業級防禦」→ Phase 2 從 Round 2 收的 full 版降階為 simple 版。Round 4 任務:寫 simple 版 brief,丟 codex xhigh 看有沒有漏 / 有沒有「明天就會出事」的點。

## 2. Simple vs Full 對比

| Round 2 full | Round 4 simple |
|---|---|
| 12 個新 column + 2 UNIQUE constraint | **4 個新 column,沒 UNIQUE 強制(改用 deterministic id)** |
| TypedPayloadError validator(防 catastrophic regex) | **不驗,gemma4 自己出什麼就存什麼** |
| 11-state lifecycle 狀態機 + CHECK constraint | **沿用既有 5 state** |
| generator_metadata 11 欄 + prompt_artifact_id | **不存,debug 看 events.daily_curation_summary** |
| candidate_sources JSONB array of typed object | **source_event_id 一個 column 指 daily summary** |
| status_changed event same-transaction | **不寫** |

## 3. Codex Round 4 review — conditional GO

完整 codex output:`.claude/jobs/1d06a75b/round04_output.md`

### 3.1 codex 支持的點
- **改 NOT NULL → NULL-able** 對(不選 sentinel — sentinel 會製造假資料,Phase 3/4 容易把假 failure / artifact 當真)
- 「這張小紙條不是 artifact patch」改 NULL-able 比較誠實
- Simple 版 scope 對

### 3.2 codex 要加 2 件最小事(我全收)

**第一件:type whitelist(不只擋 intent)**
- 我原 brief 只對 `actionable.type == 'intent'` 寫 rejected event
- codex catch:gemma4 可能吐 `keywords`(s 結尾)/ `availability_keyword`(prefix 多寫)/ 空值 / 未來新 type → 全部漏進候選表變髒資料
- 修法:**whitelist `{'keyword', 'regex'}`,其他全 reject 寫 events.improvement_candidate_rejected**

**第二件:candidate idempotency(不雙寫)**
- 我原 brief 假設「events.daily_curation_summary uuid5 idempotent 已防雙寫」
- codex catch:events 防的是 summary 自己,**candidate INSERT 本身不防**。cron 重跑 / 人工補跑 / 半路失敗重跑都會雙寫
- 修法:**candidate.id = uuid5(NAMESPACE, f"{source_event_id}:{proposal_index}") + ON CONFLICT (id) DO NOTHING**
- 這不是 Round 2 那個複雜的 hash envelope,只是把 candidate id 改成 deterministic

### 3.3 codex 沒要求但建議的 dry-run

prod 真跑前先用 transaction rollback 預演,看會建幾張、typed_payload 長相對不對。**理由不是 INSERT 危險,而是 Phase 3 Telegram 批准 UI 還沒有,髒候選進去只能人工清**。我接受。

## 4. Round 5 實作 plan(對齊 Gary 流程 1-4)

### 規劃(已 Round 4 完成)

| 動作 | 對應檔 | 已決定 |
|---|---|---|
| improvement_candidates 加 4 column | `closed_loop_kernel/postgres.py` | proposal_type, typed_payload, source_event_id, approved_by 全 NULL-able |
| 既有 9 個 NOT NULL 改 NULL-able | `closed_loop_kernel/postgres.py` ALTER | failure_id / target_artifact_* / patch_type / proposed_content / validation_assertions / rollback_plan |
| daily_curate 加 INSERT candidate 段 | `scripts/op_assistant/op_assistant_daily_curate.py` | type whitelist + uuid5 deterministic id + ON CONFLICT DO NOTHING |
| Tests | `tests/test_op_assistant_phase2_candidates.py`(新) | INSERT happy / unknown type → reject / 重跑 idempotent |

### 寫程式(Round 5 動)
### 實際運作(Round 5 動)
1. dry-run mode(env `OP_PHASE2_DRY_RUN=1` → wrap in transaction + rollback)→ 印 N candidates + typed_payload 樣本
2. 真跑(去掉 env)→ 寫進 prod op_assistant_kernel

### 驗證(Round 5 動)
1. 跑前 candidate count baseline
2. 跑後 SQL 查 improvement_candidates WHERE proposal_type IS NOT NULL ORDER BY created_at DESC
3. 驗 proposal_type / typed_payload / source_event_id / status('draft') 對
4. 同 daily_curate 再跑一次,verify candidate count 不增(idempotency)

## 5. Karpathy lens

- **#1 Think Before Coding**:codex 抓出我 silently 假設「gemma4 type 只會吐 keyword/regex/intent 三種」、「events idempotent 等於 candidate idempotent」— 兩個 silently assumption 都被 surface 修
- **#2 Simplicity First**:Round 4 simple 版維持 — 加的 2 件是「最小」(type whitelist + uuid5 deterministic),沒滑回 Round 2 full 版
- **#3 Surgical Changes**:schema migration 用 `ALTER COLUMN ... DROP NOT NULL`(不重建表 / 不改 CHECK constraint),既有 V0.2 INSERT path 不受影響
- **#4 Goal-Driven Execution**:success criteria 明確 5 條 + Round 5 verify SQL 寫死

## 6. Artifacts

- brief:`.claude/jobs/1d06a75b/round04_phase2_simple_brief.md`
- codex output:`.claude/jobs/1d06a75b/round04_output.md`
- Next:Round 5(規劃→程式→運作→驗證 commit chain)
