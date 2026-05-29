# Round 05 — Phase 2 simple 版 ship 到 production

**Date**:2026-05-29
**Participants**:Claude(implement + verify),codex Round 4 spec 為 reference
**Round 5 status**:Phase 2 simple 版 production verified — 流程 1-4 全綠

---

## 1. 情境

Gary 2026-05-29 拍板 Phase 2 simple 版 + codex Round 4 conditional GO(加 type whitelist + uuid5 deterministic id 兩件最小事)。Round 5 是 implement + production verification 階段,跟 Gary 給的流程 1-4 一對一映射。

## 2. 流程 1(規劃)→ Round 4 已完成

Spec collapsed in Round 4。沒事可動。

## 3. 流程 2(寫程式)

### 3.1 schema migration

`closed_loop_kernel/postgres.py` 加 14 個 idempotent ALTER:

```sql
-- 加 4 個 op-assistant 專用 column
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS proposal_type TEXT;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS typed_payload JSONB;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS source_event_id UUID;
ALTER TABLE improvement_candidates ADD COLUMN IF NOT EXISTS approved_by TEXT;

-- 既有 10 個 NOT NULL 改 NULL-able(simple 版不走 artifact-patch 路線)
ALTER TABLE improvement_candidates ALTER COLUMN failure_id DROP NOT NULL;
... (9 more)
```

從 14 column → 18 column,10 NOT NULL → NULL-able。

### 3.2 daily_curate.py 加 `_persist_candidates`

`scripts/op_assistant/op_assistant_daily_curate.py` 加:
- `CANDIDATE_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000003")` — Phase 2 專用 NS
- `ALLOWED_PROPOSAL_TYPES = frozenset({"keyword", "regex"})` — type whitelist
- `_persist_candidates(store, summary_event_id, actionables, dry_run=False)` 函式 — 對每個 actionable 跑 type 檢查 + deterministic id + INSERT
- `run()` 整合:`daily_curation_summary` INSERT 完後立即 call `_persist_candidates`
- `OP_PHASE2_DRY_RUN=1` env 啟 dry-run mode(印預覽,不真寫)

關鍵實作細節(codex Round 4 要求的 2 件):
- type whitelist:`raw_type = (actionable.get("type") or "").strip().lower()`;不在 whitelist 直接走 reject path
- 候選 id:`uuid.uuid5(CANDIDATE_NAMESPACE, f"{summary_event_id}:{index}")` + `ON CONFLICT (id) DO NOTHING`

### 3.3 Tests

新檔 `tests/test_op_assistant_phase2_candidates.py`(11 個 unit test):

- WhitelistTests × 4:keyword/regex/intent reject/unknown type label reject
- IdempotencyTests × 4:re-run no double write/deterministic id/不同 index 不同 id/**reject path 也 deterministic id**(下面 bug fix 後加的)
- DryRunTests × 1
- MixedActionableTests × 2

## 4. 流程 3(實際運作)

### 4.1 schema migration apply 到 production op_assistant_kernel

`docker exec op-assistant-kernel psql ... -c "ALTER TABLE..."`(idempotent,可重跑無害)。

verify:`SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='improvement_candidates'`→ 從 14 row 變 18 row。

### 4.2 Dry-run

```
OP_PHASE2_DRY_RUN=1 python scripts/op_assistant/op_assistant_daily_curate.py
```

輸出(完整 captured):
```
[DRY-RUN] would INSERT candidate id=3f356f63 type=availability_keyword preview={"type": "keyword", "value": "沒有賣完", "reason": "在決策樣本和失敗紀錄中,用戶多次詢問剩餘的、未售罄的團體資訊"...
[DRY-RUN] would INSERT candidate id=1299448b type=availability_regex preview={"type": "regex", "value": "有哪些團.*?沒有賣完", "reason": "捕捉包含『有哪些團』和『沒有賣完』的複合查詢"...
[DRY-RUN] would reject actionable[2] raw_type='intent'
daily curate 2026-05-29 [DRY-RUN]: inbound=19 attempts=3 failures=1 patterns=3 gaps=1 candidates=2 rejected=1
```

shape 正確,沒寫進 DB。

### 4.3 Real run

baseline:`SELECT COUNT(*) FROM improvement_candidates WHERE proposal_type IS NOT NULL` → 0

跑:`python scripts/op_assistant/op_assistant_daily_curate.py`

result:`candidates=2 rejected=1`

### 4.4 Verification SQL

```sql
SELECT id, status, proposal_type, typed_payload->>'value' AS payload_value,
       source_event_id, created_at
FROM improvement_candidates WHERE proposal_type IS NOT NULL
ORDER BY created_at DESC;
```

```
3f356f63-1a3e-539b-9478-a59dcb476611 | draft | availability_keyword | 沒有賣完          | e022a3b5-...
1299448b-e68e-5df8-a019-7f848f32d6d2 | draft | availability_regex   | 有哪些團.*?沒有賣完 | e022a3b5-...
```

```sql
SELECT event_type, payload->>'reason', payload->>'raw_type', payload->>'proposal_index'
FROM events WHERE event_type='improvement_candidate_rejected';
```

```
improvement_candidate_rejected | proposal_type_not_in_whitelist | intent | 2
```

兩 candidate 同 `source_event_id`(`e022a3b5-...` = today's daily_curation_summary uuid5)。同 timestamp。Status=draft。Payload 對應 gemma4 actionable。

## 5. 流程 4(驗證 — idempotency)

### 5.1 第二次 daily_curate(發現 bug)

跑同 daily_curate 第二次:

```
candidates: stays at 2 ✅
reject_events: 1 → 2 ❌
```

**bug**:`_persist_candidates` reject 路徑用 `str(uuid.uuid4())`(隨機),每次 re-run 都建新 event row;但 candidate 路徑用 uuid5(deterministic)+ ON CONFLICT 保護。

### 5.2 fix(同 Round 5 code 修)

reject path 改用同 namespace + namespace key `f"reject:{summary_event_id}:{index}"`:

```python
reject_event_id = str(uuid.uuid5(
    CANDIDATE_NAMESPACE,
    f"reject:{summary_event_id}:{index}",
))
store.execute(
    "INSERT INTO events (...) VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
    [reject_event_id, ...]
)
```

加 test:`test_reject_event_id_is_deterministic` → 跑兩次 reject 同 actionable,確認 id 相同。

### 5.3 final verify

1. 清掉 bug 期間建的 2 筆 duplicated reject events:`DELETE FROM events WHERE event_type='improvement_candidate_rejected' AND created_at > NOW() - INTERVAL '15 minutes'` → DELETE 2
2. 跑 daily_curate 兩次
3. 結果:

| | n |
|---|---|
| candidates | 2 |
| reject_events | 1 |

**完全 idempotent**。

## 6. Karpathy lens

- **#1 Think Before Coding**:dry-run mode 我加進 brief 但實作時想到「dry-run 還會 push Telegram 嗎」— 想了一下不擋(因為 Gary 已習慣每天 push;dry-run 只擋 candidate INSERT)
- **#2 Simplicity First**:沒 hash envelope / 沒 lifecycle 狀態機 / 沒 generator_metadata,跟 Round 4 spec 一致
- **#3 Surgical Changes**:既有 V0.2 INSERT path 完全不動;schema migration 加 column + 改 NULL-able,沒重建表
- **#4 Goal-Driven Execution**:success criteria 5 條 — pytest 全綠 ✅ / production INSERT 至少 1 row ✅ / row 欄位對 ✅ / V0.2 不受影響 ✅(daily_curation_summary 仍 idempotent)/ V0.3 doc Phase 2 spec patch 待 commit 完成

## 7. 成果

| 項目 | 狀態 |
|---|---|
| pytest 11/11 pass | ✅ |
| production schema migration | ✅ idempotent,14→18 column |
| production candidates | ✅ 2 rows(keyword + regex)|
| production reject event | ✅ 1 row(intent) |
| idempotency(daily_curate × 2) | ✅(bug fix 後) |
| code-level reject idempotency 新 test | ✅(test_reject_event_id_is_deterministic) |

Phase 2 simple 版 production live。Phase 3 開工 ready。

## 8. Artifacts

- `closed_loop_kernel/postgres.py` 加 14 ALTER 段
- `scripts/op_assistant/op_assistant_daily_curate.py` 加 `_persist_candidates` 函式
- `tests/test_op_assistant_phase2_candidates.py` 新檔(11 unit tests)
- production op_assistant_kernel.improvement_candidates 表新增 2 row
- production events.improvement_candidate_rejected 1 row
