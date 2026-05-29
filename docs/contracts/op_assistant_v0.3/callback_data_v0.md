# Contract: Telegram callback_data v0

**Phase consumers**: 3 (sender), 4 (parser), 8 (KILL handler)
**Locked**: Round 7 (2026-05-29)

Telegram inline keyboard `callback_data` is hard-capped at **64 bytes**. This contract pins the exact format so Phase 3 (which writes it) and Phase 4 (which parses it) can ship in parallel without contract drift.

## Format

Two shapes, both well under Telegram's 64-byte cap.

**Per-candidate actions** (`apv`/`rej`/`vw`/`kill`):

```text
<action>:<candidate_uuid_hex32>
```

- `action` ∈ {`apv`, `rej`, `vw`, `kill`} — 2-4 ASCII chars, lowercase
- `:` single colon
- `candidate_uuid_hex32` = full UUID hex form (dashes stripped) of `improvement_candidates.id`

Max length: `4 + 1 + 32 = 37` bytes.

**Daily-summary-wide KILL** (`killall`):

```text
killall:<daily_summary_uuid_hex32>
```

- `killall` is the only multi-target action
- The hex32 is the `events.daily_curation_summary.id` (same uuid5 that Phase 2 writes as `source_event_id` on each candidate)
- The dispatcher reads `improvement_candidates WHERE source_event_id = ?` to expand the kill list server-side

Max length: `7 + 1 + 32 = 40` bytes.

Codex Round 7 caught the original 8-hex-prefix design as a bad trade: saving 24 bytes is not worth introducing collision lookup, stale-button ambiguity, or accidentally killing the wrong candidate. The full 32-hex form removes all three risks at zero cost since Telegram's cap is 64.

## Action taxonomy

| action | when Gary taps it | dispatcher does (Phase 4) |
|---|---|---|
| `apv` | ✅ approve the candidate | atomic transaction: lock candidate, INSERT approvals row, UPDATE status `draft` → `approved`, INSERT `events.candidate_status_changed`; triggers sandbox replay job (Phase 6) |
| `rej` | ❌ reject the candidate | atomic transaction: lock candidate, INSERT approvals row with `decision='rejected'`, UPDATE status `draft` → `rejected`, INSERT event; reply with reject UX (see approval_audit_v0.md) |
| `vw` | 🔍 view sandbox result (Phase 6+) | read-only: SELECT `sandbox_runs` most recent for this candidate; reply summary; mutate nothing |
| `kill` | 💥 KILL one applied patch (Phase 8) | atomic transaction: lock candidate, INSERT approvals row with `decision='killed'`, UPDATE status `applied` → `killed`, INSERT event; trigger `git revert` of the applied commit |
| `killall` | 💥 KILL every applied patch from a given daily summary | dispatcher expands `daily_summary_id` → list of `candidate_id` where status=`applied`; loops the per-candidate kill transaction for each; replies with the batch summary described below |

### `killall` partial-success reporting (Round 7.5 codex sharpening)

A batch kill may have any of its per-candidate transactions hit `stale` (status no longer `applied`), `unknown_candidate`, or other rollback states. The dispatcher reply is a structured summary so Gary never sees an ambiguous "success" when some kills silently failed:

```text
💥 KILL 結果:
  ✅ 已 KILL: 3 條(候選 1, 候選 3, 候選 5)
  ⏭ 已過期跳過: 2 條(候選 2 早就被 KILL 過 / 候選 4 還沒 applied)
  ❌ 系統失敗: 0 條

(全部 5 條都處理完了)
```

Each per-candidate result is recorded as its own `events.candidate_status_changed` (for success) or `events.telegram_callback_stale` (for skip) row, so the audit chain is identical to the per-`kill` action — `killall` is purely a UI convenience, not a new audit shape.

V0.3 simple version **does not include payload_hash** in callback_data — Phase 2 (Round 5) deferred hash chain to V0.4. Stale-button replay attacks are mitigated server-side by `SELECT ... FOR UPDATE` + status check inside the dispatcher transaction (see approval_audit_v0.md); a stale tap writes `events.telegram_callback_stale` and replies "this button has been used", it does **not** create an approvals row.

## Parser regex (Phase 4)

```python
import re

CALLBACK_PER_CANDIDATE_RE = re.compile(r"^(apv|rej|vw|kill):([0-9a-f]{32})$")
CALLBACK_KILLALL_RE       = re.compile(r"^killall:([0-9a-f]{32})$")

def parse_callback(data: str) -> tuple[str, str] | None:
    """Returns (action, target_id_hex32) or None if invalid.
    For killall, action='killall' and target_id is the daily_summary_id.
    """
    m = CALLBACK_PER_CANDIDATE_RE.fullmatch(data)
    if m:
        return (m.group(1), m.group(2))
    m = CALLBACK_KILLALL_RE.fullmatch(data)
    if m:
        return ("killall", m.group(1))
    return None
```

No flexibility, no fallback. Non-matching callback_data → audit-log `events.telegram_callback_malformed` and ignore (no LLM interpretation, no fuzzy match, no truncation acceptance).

## Multi-row keyboard layout (Phase 3 sender)

Per candidate, the daily Telegram message includes one keyboard row:

```
[✅ 批准 1]  [❌ 拒絕 1]  [🔍 看 1 sandbox]
[✅ 批准 2]  [❌ 拒絕 2]  [🔍 看 2 sandbox]
...
[💥 KILL 今天全部已套用(緊急)]
```

The `💥 KILL 今天全部已套用` row is rendered with `callback_data='killall:<daily_summary_id_hex32>'` only when **any** candidate from this daily summary has reached `status='applied'`. Otherwise omitted (avoids a button that resolves to an empty kill list).

Individual `kill` buttons (per-applied-candidate) are surfaced in a separate "已套用清單" follow-up message Phase 3 sends after canary completion, not in the morning approval message.

## Examples

```text
apv:3f356f631a3e539b9478a59dcb476611       # approve specific candidate
rej:1299448be68e5df8a0197f848f32d6d2       # reject specific candidate
vw:3f356f631a3e539b9478a59dcb476611        # show sandbox metrics for it
kill:3f356f631a3e539b9478a59dcb476611      # KILL one applied patch
killall:e022a3b562cc580eb3bd8d2f02a38e14   # KILL every applied patch from this daily summary
```

## Why this format collision-free

The candidate id is a full UUID (122-bit randomness; PostgreSQL `gen_random_uuid()`). Two candidates colliding requires `2^61 ≈ 2.3 × 10^18` candidates by birthday bound — effectively impossible at OP scale. The 8-char prefix the original draft proposed had `2^32 ≈ 4.3 × 10^9` keyspace; codex Round 7 correctly flagged that as cheap convenience with expensive worst case.

## Backwards compat

V0.3 callback_data `v0`. Future revisions:
- `v1`: add payload_hash prefix (if hash chain comes back in V0.4)
- `v2`: change `kill` semantics to revert by `applied_at` window (Phase 8 refinement)

Until then, dispatcher parser must reject any callback_data that doesn't match this exact `v0` regex.
