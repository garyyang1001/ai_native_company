# Round 03 — R18 spike + Phase 2 開工決策

**Date**:2026-05-29
**Participants**:Claude Opus 4.7(spike alone,無 codex — pure factual investigation)
**Round 3 status**:collapsed — R18 結論 + Phase 2 開工降階決策

---

## 1. R18 spike — failures → inbound 鏈穩定性

Round 2 codex implicit assumption #2:「`failures` 是否穩定連回原始 inbound event,U39 依賴這條鏈」。Phase 2 開工前必驗。

### 1.1 spike 步驟

1. Read `closed_loop_kernel/postgres.py`:`failures.attempt_id → attempts.event_id → events.id` 路徑名義上存在(`attempts.event_id UUID REFERENCES events(id)`)
2. PG query production op_assistant_kernel(2 個 production failures,3 個 attempt_envelopes)
3. Verify source_refs UUID 是否真在 events 表

### 1.2 真實狀態 — chain broken

```sql
-- query 1: failures → attempts → events
SELECT f.id, f.attempt_id, a.event_id, e.event_type
FROM failures f
LEFT JOIN attempts a ON a.id = f.attempt_id
LEFT JOIN events e ON e.id = a.event_id;

failure_id                    | attempt_id  | attempt_event_id | root_event_type
f96cbb59-...                  | 602f...     | (NULL)           | (NULL)
ef0d452f-...                  | 9b32...     | (NULL)           | (NULL)
```

`attempts.event_id` **全部 NULL**。 V0.2 adapter `_op_write_pg` 寫 attempt 時 `event_id` 沒帶。

```sql
-- query 2: attempt_envelopes.source_refs → events
SELECT a.attempt_id, e.source_refs->>0 AS ref_id, ev.event_type
FROM attempt_envelopes e
JOIN attempts a ON a.id = e.attempt_id
LEFT JOIN events ev ON ev.id::text = e.source_refs->>0;

attempt_id  | ref_id                                | event_type
602f...     | de9c26b1-8b74-5ec6-b3c6-df5ce1e7cd6d  | (NULL)
6d57...     | 5cb9cd11-b5bb-539c-ac3b-9d1224cea668  | (NULL)
b9b1...     | 1636a627-127f-5655-a10c-043dc5809c87  | (NULL)
```

`source_refs` 內 UUID 像 uuid5,但**不存在 events 表**。V0.2 adapter 算 source_refs 用的 seed 跟 events.op_assistant_line_inbound 的 uuid5 seed **不同**。兩個 hash 計算路徑不對齊。

### 1.3 結論

**production chain 完全斷**。Round 2 U39 spec 「優先 curated_failure inbound link」現狀無法實現。

## 2. 兩個 mitigation 選項

| Option | 動作 | 動 V0.2 production code? | Phase 2 工 | 整體影響 |
|---|---|---|---|---|
| **A. 修 V0.2 adapter** | 改 `plugins/op-assistant-line/adapter.py` `_op_write_pg`:寫 attempt 時帶 `event_id`;同時讓 `source_refs` reuse events.id | ✅ 動 LINE plugin(風險:V0.2 production live,改錯 bot 掛) | 推遲 Phase 2 半天 | chain 修好,U39 spec 不變,但 backfill 困難(歷史 attempts 不能補) |
| **B. V0.3 用 substring fallback,V0.4 修 V0.2** | 接受 chain 斷;U39 `candidate_sources` 全用 `source_type='substring_match'` confidence 0.5;V0.4 修 adapter | ❌ V0.2 不動 | Phase 2 立刻開工 | U39 trace 弱化但不致命;V0.3 ship 不被 R18 卡 |

### 我的決定:**選 B**

理由:
- **Karpathy 2 simplicity**:V0.3 不擴 scope 動 V0.2 production code(must-not-touch 原則)
- **Karpathy 3 surgical**:R18 fix 不該跟 Phase 2 candidate ingest 綁一起 — 不同 concern
- **Goal-driven**:Phase 2 不為了完美 trace 推遲;substring match 對 V0.3 first ship 夠用(我們知道 gemma4 actionable.value 出自 fail preview)
- **V0.4 升級路徑**:加 `failures.inbound_event_id` direct FK + V0.2 adapter backfill 邏輯,屆時 historical candidate 重 backfill `candidate_sources`

### 2.1 Phase 2 U39 spec 微調(從 Round 2 final)

```python
# Round 2 spec:
{
    "source_type": "failure",            # 不再 default
    "source_id": "<failures.id>",
    "inbound_event_id": "<events.id>",   # NULL until V0.4
    "match_reason": "curated_failure",   # 改 default
    "confidence": 1.0,                   # 改 default
}

# Round 3 修訂(V0.3 default):
{
    "source_type": "substring_match",     # V0.3 預設
    "source_id": "<failures.id>",         # 我們知道 failure_id,但 chain 到 inbound 斷
    "inbound_event_id": null,             # V0.4 chain 修好後填
    "match_reason": "actionable_value_in_failure_preview",
    "confidence": 0.5,                    # heuristic 不是 curated
}
```

Phase 6 replay 因 inbound_event_id NULL → 用 `failures.context.message_preview_redacted` 直接 feed query_parser(reduced fidelity 但可運作)。

## 3. R19 加入風險登錄

R18 結論為「production chain broken」,新增 R19 追蹤 V0.4 修法:

| R19 | V0.2 adapter `attempts.event_id` + `attempt_envelopes.source_refs` 沒對齊 events.id;causes U39 chain broken in V0.3 | V0.3 用 substring fallback;V0.4 改 adapter 寫入時帶 inbound event_id + reuse events.id 為 source_refs;backfill 歷史 row 困難(可接受) |

## 4. Round 3 後 Phase 2 開工 ready 狀態

| 項目 | 狀態 |
|---|---|
| 12 個 schema column | ✅ Round 2 spec |
| candidate lifecycle 狀態機 | ✅ Round 2 spec(11 states + CHECK + Python enum) |
| payload_hash envelope | ✅ Round 2 spec |
| typed_payload validator(防 -O / 防 catastrophic regex) | ✅ Round 2 spec |
| generator_metadata + prompt_artifact_id | ✅ Round 2 spec |
| candidate_sources | ✅ Round 3 修訂 spec(全 substring,confidence 0.5) |
| idempotency(curation_run_id + proposal_index UNIQUE) | ✅ Round 2 spec |
| status_changed event 同 transaction | ✅ Round 2 spec |
| new_intent 直接 reject 到 events.improvement_candidate_rejected | ✅ Round 2 spec |

**Phase 2 brief 可寫,開工 ready**。

## 5. Phase 2 implement 路線

下一個 round / commit chain:

1. 寫 `phase2_brief.md`(基於 Round 2 + 3 final spec)
2. 我 implement(`closed_loop_kernel/postgres.py` migration + `scripts/op_assistant/op_assistant_daily_curate.py` 改造 + tests)
3. codex high effort review
4. patch fix
5. codex xhigh review
6. patch fix
7. ship Phase 2 → mark task #7 completed

預計 1-2 commit chain。

## 6. Karpathy lens

- **#1 Think Before Coding**:R18 spike 證實 implicit assumption 真的 broken,如果直接 implement U39 curated-link 邏輯會在 production 抓不到任何 source
- **#2 Simplicity First**:選 B(substring fallback)不 A(動 V0.2)避免 scope creep
- **#3 Surgical Changes**:V0.2 production code 不碰;U39 spec 微調最小
- **#4 Goal-Driven Execution**:R18 真實 verify(production query)→ 接受降階 → Phase 2 開工 ready

## 7. Artifacts

- R18 PG queries:本 doc §1.2 SQL
- Production sample 2 failures / 3 attempt_envelopes 結果
- 結論:`attempts.event_id` NULL + `source_refs` UUID 不對齊 events
- 無 codex consult 本 round(pure factual spike,LLM 不需介入)
