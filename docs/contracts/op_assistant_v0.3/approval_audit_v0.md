# Contract: approval audit v0

**Phase consumers**: 4 (dispatcher writes), 5 (audit reader), 6 (replay trigger), 8 (canary trigger)
**Locked**: Round 7 (2026-05-29)

Gary's button press in Telegram is **not** an approval record. It's a transport signal. The contract here is what the **kernel** records when the dispatcher (Phase 4) translates that signal into a durable decision.

## `approvals` table schema delta

V0.2 has:

```sql
CREATE TABLE approvals (
    id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES improvement_candidates(id),
    approved_by VARCHAR(100) NOT NULL,
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected')),
    comments TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

V0.3 Phase 4 dispatcher ALTER (additive, NULL-able):

```sql
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS approval_channel TEXT;       -- 'telegram' / 'web' / 'cli'
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS source_event_id UUID;        -- events.telegram_inbound id (the callback_query that triggered this)
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS channel_message_id TEXT;     -- Telegram callback_query.id for cross-reference
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS reject_reason TEXT;          -- machine-readable reason when decision='rejected' or 'killed'

-- Round 2 codex U11: three-layer race protection
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS approvals_decision_check;
ALTER TABLE approvals ADD CONSTRAINT approvals_decision_v03_check
    CHECK (decision IN ('approved', 'rejected', 'killed'));

-- Codex Round 7.5 caught: PostgreSQL ON CONFLICT can match a partial unique
-- index only if the INSERT carries the same WHERE predicate, which is brittle.
-- We use a full unique index instead — multiple NULLs do not violate uniqueness
-- (PG defaults to NULLS DISTINCT), so V0.2 OHYA-demo rows with source_event_id
-- IS NULL still coexist, and ON CONFLICT (source_event_id) DO NOTHING matches
-- this index cleanly for every Phase 4 dispatcher INSERT.
CREATE UNIQUE INDEX IF NOT EXISTS approvals_source_event_unique
    ON approvals (source_event_id);

-- Round 2 codex U11: per-candidate final-decision uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS approvals_candidate_final_unique
    ON approvals (candidate_id) WHERE decision IN ('approved', 'rejected');
```

`approvals` stays **append-only** (per V0.2 §9 — `prevent_mutation` trigger). Codex Round 7 caught the original draft's contradiction: "re-approve = new row" cannot coexist with `approvals_candidate_final_unique`. V0.3 chooses the unique index: **each candidate has at most one final decision (`approved` / `rejected`)**, and a later `killed` is allowed because the unique index excludes it from the constraint. Re-approve is not supported in V0.3; a re-tap of the same decision returns "already processed" without writing a new approvals row.

Kill after approve = a new approvals row with `decision='killed'`. The decision-uniqueness index blocks the "two `approved` rows for one candidate" race; the `source_event_id` index blocks dispatcher restart from double-claiming the same Telegram callback.

## Dispatcher transactional claim (Phase 4 implementation)

Codex Round 7 found the original draft had INSERT-then-UPDATE order: a UPDATE failure after a successful INSERT would leave a half-approval (`approvals` row exists, candidate status unchanged). V0.3 inverts the order: **lock the candidate first, check status before any write, then INSERT + UPDATE + audit inside a single transaction**. Anything that fails mid-way rolls the whole thing back.

```python
def claim_and_apply(conn, *, source_event_id: str, candidate_id: str,
                     decision: str, approved_by: str,
                     channel_message_id: str | None,
                     reject_reason: str | None) -> ClaimResult:
    """Single atomic transaction. Either every write lands or none do."""
    with conn.transaction():
        # 0. Lock the candidate row so concurrent dispatchers serialize.
        candidate = conn.execute("""
            SELECT status FROM improvement_candidates
             WHERE id = %s FOR UPDATE
        """, [candidate_id]).fetchone()
        if candidate is None:
            return ClaimResult.UNKNOWN_CANDIDATE

        current_status = candidate[0]
        expected_from = 'applied' if decision == 'killed' else 'draft'
        if current_status != expected_from:
            # Stale-button case. Do not touch approvals — that would corrupt
            # the audit chain. Only write the stale event for forensics.
            conn.execute("""
                INSERT INTO events (id, event_type, payload, created_at)
                VALUES (gen_random_uuid(), 'telegram_callback_stale', %s, NOW())
            """, [json_param({
                "candidate_id": candidate_id,
                "source_event_id": source_event_id,
                "current_status": current_status,
                "expected_from": expected_from,
                "attempted_decision": decision,
                "by_actor": approved_by,
            })])
            return ClaimResult.STALE

        # 1. INSERT approval (source_event_id UNIQUE blocks dispatcher restart
        #    from double-claiming the same Telegram callback).
        row = conn.execute("""
            INSERT INTO approvals (
                id, candidate_id, approved_by, decision, comments,
                approval_channel, source_event_id, channel_message_id,
                reject_reason, created_at
            ) VALUES (
                gen_random_uuid(), %s, %s, %s, NULL,
                'telegram', %s, %s, %s, NOW()
            )
            ON CONFLICT (source_event_id) DO NOTHING
            RETURNING id
        """, [candidate_id, approved_by, decision,
              source_event_id, channel_message_id, reject_reason]).fetchone()
        if row is None:
            # Same Telegram callback already processed by an earlier
            # dispatcher run. Roll back the empty event write (we're still in
            # the transaction) and return.
            raise _RollbackToAlreadyClaimed()
        approval_id = row[0]

        # 2. UPDATE candidate.status — guarded by FOR UPDATE above, so this
        #    cannot race with another approval transaction.
        next_status = {
            'approved': 'approved',
            'rejected': 'rejected',
            'killed':   'killed',
        }[decision]
        conn.execute("""
            UPDATE improvement_candidates
               SET status = %s
             WHERE id = %s
        """, [next_status, candidate_id])

        # 3. Audit event same-transaction.
        conn.execute("""
            INSERT INTO events (id, event_type, payload, created_at)
            VALUES (gen_random_uuid(), 'candidate_status_changed', %s, NOW())
        """, [json_param({
            "candidate_id": candidate_id,
            "from_status": expected_from,
            "to_status": next_status,
            "by_phase": "phase_4_dispatcher",
            "by_actor": approved_by,
            "approval_id": approval_id,
        })])

    # Transaction committed atomically; either all three writes (approval +
    # candidate UPDATE + event) landed, or none did.
    return ClaimResult.OK
```

`_RollbackToAlreadyClaimed` is a private exception caught at the outer call site to convert "second dispatcher saw same source_event_id" into `ClaimResult.ALREADY_CLAIMED` without leaving any partial writes.

The unique index `approvals_candidate_final_unique` is a defense-in-depth backstop: even if the `SELECT FOR UPDATE` somehow missed a race (it shouldn't), the unique violation surfaces in the INSERT step and rolls back the whole transaction.

## Reject UX (Round 6 codex New 3)

When `decision='rejected'` is committed, dispatcher (Phase 4) sends a Telegram reply that explains the consequence — not just "rejected".

Template:

```text
❌ 已拒絕第 {N} 招(「{typed_payload_summary}」)

接下來會發生:
• 這張候選紙條的狀態改成「拒絕」,不會進實驗室,不會改 bot 規則
• 30 天後資料庫保留期到,events 自動清掉這條建議
• 明天 gemma4 如果又看到類似訊息再提同樣建議,系統會自動 ON CONFLICT
  跳過,不會堆出兩張一樣的紙條
• 如果你後悔了,目前 V0.3 沒有「撤銷拒絕」按鈕(V0.4 評估加),要回到
  電腦改資料庫 SQL
```

`typed_payload_summary` is built from the candidate's `typed_payload`:
- keyword → `關鍵字「{value}」`
- regex → `句型「{value}」`

## Kill UX (Phase 8 button — same structure)

```text
💥 已 KILL 第 {N} 招(「{typed_payload_summary}」)

接下來會發生:
• 已套用的 patch 自動 git revert
• bot 規則回到 KILL 前的狀態
• canary state 標記 status='killed',不再 sample 流量
• 30 天後 events 保留期到自動清掉這次 KILL 紀錄
```

## "View sandbox" UX (Phase 6 button)

When candidate's most recent `sandbox_runs.status` exists:

```text
🔍 第 {N} 招 sandbox 結果

• 4 個檢查:
  - 舊客戶問句被打壞: {regression_count} 條(必須 0)
  - 原本沒聽懂被新規則救回: {improvement_count} 條(至少 1)
  - 一句話命中多個意圖: {ambiguity_count} 條(必須 0)
  - 新規則太貪(30 天 unclear 命中率): {over_greedy_rate}%(必須 <50%)
• 整體判定: {passed/failed}
• 跑了 {corpus_size} 條歷史對話,用 {duration_ms}ms

{passed ? "建議:可以 ✅ 批准" : "不建議批准,原因: {fail_reason}"}
```

If sandbox hasn't run yet (Phase 6 not triggered): "Sandbox 還沒跑,先按 ✅ 批准會自動觸發 sandbox replay。"

## Reviewer separation enforcement points

Per cross-cutting rule in [README.md](README.md), the rule is **role-based**, not table-based. The Phase 4 transaction above is *expected* to write to three tables (`approvals` + `improvement_candidates` + `events`) — that single transaction is the atomic record of one Approver action. What's forbidden is one actor holding two roles.

| actor | role | may write to |
|---|---|---|
| `gemma4` (Phase 2 daily_curate) | **Proposer** only | `improvement_candidates` (initial draft), `events` (audit) |
| Phase 4 dispatcher (acting on Gary's Telegram tap) | **Approver record-keeper** only | `approvals`, `improvement_candidates.status`, `events` — all in one transaction |
| Phase 6 sandbox replay | **Verifier** only | `sandbox_runs`, `improvement_candidates.status` (`approved` → `sandbox_verified`/`sandbox_failed`), `events` |
| Phase 7 patch emitter | **Applier** only | git commit + `improvement_candidates.status` (`sandbox_verified` → `patch_emitted` / `patch_too_invasive`), `events` |
| Phase 8 canary judge | **Auto-reverter** only | git revert + `improvement_candidates.status` (`patch_emitted` → `canary_running` / `applied` / `killed`), `events` |

Each module's Python code may not call any function from another role's module. If a phase needs to escalate (e.g. Phase 6 sees a candidate it can't replay), it writes `events.replay_blocked` and stops — it does not advance the candidate's status into the next role's territory.
