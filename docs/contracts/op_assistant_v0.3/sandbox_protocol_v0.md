# Contract: sandbox protocol v0

**Phase consumers**: 6 (replay engine writes), 7 (AST guard reads metrics), 8 (canary triggers on `passed`), Round 13-14 (1000-case sim)
**Locked**: Round 7 (2026-05-29)

The sandbox is a sibling PostgreSQL database that lets us re-run any approved candidate against historical inbound traffic, measure four metrics, and decide whether the patch deserves a canary deploy.

## Database layout

```text
docker container "op-assistant-kernel"
├── op_assistant_kernel          ← production (Phase 1 + 2 already write here)
└── op_assistant_sandbox_kernel  ← Round 8 first commit creates this
                                    (Phase 6 implementation requires it)
```

Codex Round 7 caught a timeline mistake: the original draft said "Round 13 creates this", but Phase 6 sandbox replay needs the sibling DB to exist before it can ship. The actual order is:

- **Round 8 first commit**: create `op_assistant_sandbox_kernel`, apply `closed_loop_kernel/postgres.py` POSTGRES_SCHEMA + the `sandbox_runs` table below.
- **Round 8-11**: Phase 6 replay engine, Phase 7 patch emitter, Phase 4 dispatcher, Phase 5 audit chain all use the sandbox DB for testing.
- **Round 13-14**: the 1000-case sim runs *inside* the already-existing sandbox DB; that round adds the seeder + expander, not the database itself.

`op_assistant_sandbox_kernel` mirrors `op_assistant_kernel`'s schema exactly (`closed_loop_kernel/postgres.py` POSTGRES_SCHEMA applied as-is) plus the `sandbox_runs` table below. No cross-DB references — sandbox runs receive a **snapshot copy** of production rows they need (failures, attempt_envelopes, events.op_assistant_line_inbound) seeded via the protocol in §4.

Why a sibling DB instead of a schema in the same DB: schema-isolation still shares the `events` retention cron, the `prevent_mutation` trigger function, and the connection pool. A separate DB gives us a clean `DROP DATABASE` blast radius without touching production write paths.

## `sandbox_runs` schema

Added to both databases (production writes when approved patches are sandbox-replayed; sandbox DB also writes for 1000-case sim):

```sql
CREATE TABLE IF NOT EXISTS sandbox_runs (
    id UUID PRIMARY KEY,                    -- see "deterministic run id" below
    candidate_id UUID NOT NULL,             -- references improvement_candidates(id) in the same DB
    seed BIGINT NOT NULL,                   -- deterministic seed for clock + fake gemma4 cache
    corpus_size INT NOT NULL,               -- how many historical rows were replayed
    corpus_snapshot_hash TEXT NOT NULL,     -- sha256(sorted row ids) of the corpus actually used
    clock_started_at TIMESTAMPTZ NOT NULL,  -- fake clock origin; sandbox treats this as "now"
    model_digest TEXT NOT NULL,             -- ollama show gemma4:e4b digest; not just name
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN (
        'running', 'passed', 'failed', 'orphaned'
    )),
    fail_reason TEXT,                       -- machine-readable when status='failed'
    duration_ms INT,                        -- how long the run took (wall clock, not fake clock)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sandbox_runs_candidate
    ON sandbox_runs (candidate_id, created_at DESC);
```

### Deterministic run id (Round 7 codex revision)

The original draft used `uuid5(SANDBOX_NS, f"{candidate_id}:{seed}")`. Codex Round 7 caught: same candidate + seed but a different `model_digest` or different `corpus_snapshot_hash` would collide to the same id, and two genuinely different runs would look identical in the table. The contract id formula is:

```python
SANDBOX_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000004")

def compute_run_id(candidate_id: str, seed: int, model_digest: str,
                    corpus_snapshot_hash: str,
                    clock_started_at: datetime) -> str:
    key = (
        f"{candidate_id}:{seed}:{model_digest}:"
        f"{corpus_snapshot_hash}:{clock_started_at.isoformat()}"
    )
    return str(uuid.uuid5(SANDBOX_NS, key))
```

Any of the five inputs changing produces a new run id. Re-running with all five identical produces the **same id and the same metrics**; the second INSERT is skipped by `ON CONFLICT (id) DO NOTHING`. (Codex Round 7.5 caught: the row is not literally byte-identical because `created_at DEFAULT NOW()`, `duration_ms`, and `completed_at` come from wall clock and would differ between runs. The deterministic guarantee is on the **id + metrics**, not on the timestamp/duration audit columns.)

## Deterministic clock + seed

A sandbox run is a pure function of `(candidate_id, seed, clock_started_at, model_digest, corpus_snapshot_hash)`. Re-running the same id must produce byte-identical `metrics`.

Implementation:

```python
class FakeClock:
    """Replaces datetime.now() and SQL NOW() inside sandbox runs."""
    def __init__(self, anchor: datetime, tick_seconds: float = 0.0):
        self._anchor = anchor
        self._offset = 0.0
        self._tick = tick_seconds

    def now(self) -> datetime:
        t = self._anchor + timedelta(seconds=self._offset)
        self._offset += self._tick
        return t

    def sql_now(self) -> str:
        return self.now().isoformat()
```

Phase 6 replay engine threads a `FakeClock` instance through every `datetime.now()` call and replaces `NOW()` in `INSERT INTO events`-style statements with literal ISO timestamps from `sql_now()`. Production paths keep using `NOW()` directly.

`seed` is computed deterministically from the candidate id. Codex Round 7 caught that the original draft's `hash(candidate_id)` would use Python's salted hash, breaking re-run determinism. The contract formula is:

```python
def compute_seed(candidate_id: str) -> int:
    """Stable across process restarts and Python versions, fits PG BIGINT."""
    raw = int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16], 16)
    # Mask to 63 bits so the value always fits PostgreSQL BIGINT (signed int64).
    # Codex Round 7.5 caught: full 64-bit unsigned can exceed 2^63 - 1.
    return raw & ((1 << 63) - 1)
```

63-bit return fits PostgreSQL `BIGINT` (signed int64) without overflow. Collision risk over `2^63 ≈ 9.2 × 10^18` candidates is well past any conceivable OP scale.

## PII anonymisation (Round 6 codex New 1)

Production `events.op_assistant_line_inbound.payload` includes `user_id` (LINE U-prefix hex) and `message_id` (LINE message id). Before any production row enters the sandbox seed, the seeder script rewrites:

```python
from wannavegtour.redact import redact_text  # phone/email scrubbing

def anonymise_inbound(row: dict, seed: int) -> dict:
    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    # Hash user_id and message_id with seed so they're stable across re-runs
    # but unlinkable to the real LINE account.
    payload["user_id"] = "U" + hashlib.sha256(
        f"{seed}:{payload.get('user_id', '')}".encode()
    ).hexdigest()[:32]
    payload["message_id"] = hashlib.sha256(
        f"{seed}:{payload.get('message_id', '')}".encode()
    ).hexdigest()[:24]
    payload["group_id"] = ""   # never carry group id into sandbox
    # Codex Round 7 caught: do NOT trust that the historic row was already
    # redacted by the live pipeline. Re-run redact on the body so any drift
    # in the redaction rules (or any row written before redaction shipped)
    # gets re-scrubbed here.
    payload["text"] = redact_text(payload.get("text", ""))
    row["payload"] = payload
    return row
```

The seeder writes its own `events.sandbox_seeded` row with the original production row id, the seed used, and a sha256 of the anonymised payload — so we can prove no real LINE user id ever left production.

## Replay corpus

Phase 6 replay loads three slices of historical inbound (from the sandbox copy, not production):

1. **24-hour failure corpus** — `failures` rows from the most recent 24-hour fake-clock window. Phase 6 must show **at least one improvement** here (`improvement_count >= 1`).
2. **7-day success regression** — `attempt_envelopes` rows where `machine_record.parser_intent != 'unclear'` from the prior 7 fake-clock days. Must produce zero regressions (`regression_count == 0`).
3. **30-day unclear sample** — `events.op_assistant_line_inbound` rows over the last 30 fake-clock days, filtered to those that produced an `unclear` parse. Used for over-greedy check.

Corpus snapshot hash: codex Round 7.5 caught that hashing only sorted row ids is too weak — if the anonymise function later changes (or row payload drifts in-place via a future schema migration), the hash would stay the same even though the actual corpus content the replay saw is different. The contract is:

```python
def compute_corpus_snapshot_hash(corpus_rows: list[dict]) -> str:
    """Stable hash of both the row identities AND the anonymised payloads
    that the replay engine actually reads. Re-running with the same row
    set but a changed anonymise function produces a different hash, so
    the run id (which embeds this hash) differs and we know the result
    is not directly comparable to the prior run.
    """
    sorted_rows = sorted(corpus_rows, key=lambda r: str(r["id"]))
    h = hashlib.sha256()
    for row in sorted_rows:
        h.update(str(row["id"]).encode("utf-8"))
        h.update(b":")
        payload_canon = json.dumps(
            row.get("payload", {}), sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        h.update(hashlib.sha256(payload_canon).digest())
    return h.hexdigest()
```

Written to `sandbox_runs.metrics.corpus_snapshot_hash` (and also fed into `compute_run_id` so the run id is sensitive to payload drift, not just row identity).

## Four metric calculation

```python
def compute_metrics(corpus_24hr_failures: list,
                     corpus_7d_success: list,
                     corpus_30d_unclear: list,
                     patched_parser: ModuleType,
                     original_parser: ModuleType) -> dict:
    # Metric 1: regression
    regression_count = sum(
        1 for row in corpus_7d_success
        if patched_parser.parse_query(row["text"]).intent.value !=
           original_parser.parse_query(row["text"]).intent.value
    )
    # Metric 2: improvement
    improvement_count = sum(
        1 for row in corpus_24hr_failures
        if patched_parser.parse_query(row["text"]).intent.value != "unclear" and
           original_parser.parse_query(row["text"]).intent.value == "unclear"
    )
    # Metric 3: ambiguity (V0.3: parser only returns one intent so always 0;
    # placeholder for V0.4 multi-intent dispatch)
    ambiguity_count = 0
    # Metric 4: over-greedy (new rule grabs too much of unclear corpus)
    if len(corpus_30d_unclear) == 0:
        over_greedy_rate = 0.0
    else:
        newly_matched = sum(
            1 for row in corpus_30d_unclear
            if patched_parser.parse_query(row["text"]).intent.value != "unclear" and
               original_parser.parse_query(row["text"]).intent.value == "unclear"
        )
        over_greedy_rate = newly_matched / len(corpus_30d_unclear)
    return {
        "regression_count": regression_count,
        "improvement_count": improvement_count,
        "ambiguity_count": ambiguity_count,
        "over_greedy_rate": round(over_greedy_rate, 4),
    }
```

## Pass criteria

A sandbox run is `passed` iff **all** of:

```python
metrics["regression_count"] == 0 and
metrics["improvement_count"] >= 1 and
metrics["ambiguity_count"] == 0 and
metrics["over_greedy_rate"] < 0.50
```

Anything else → `failed` with `fail_reason` set to the first violated metric.

### Metric scope honesty (Round 7 codex sharpening)

Codex Round 7 correctly flagged these four metrics as **intent-level only**:

- `regression_count` compares `parse_query().intent` between original and patched parser — it does **not** compare handler output (`fetch_wc_data` response, `compose_reply` text, send result). A patch that produces the same intent but a worse downstream answer would pass this metric.
- `ambiguity_count` is a hard-coded `0` in V0.3 because the parser is single-intent; it's a placeholder for V0.4 multi-intent dispatch.

V0.3 ships with this safety net acknowledging the gap. V0.4 widens metrics to handler-level (replay the WooCommerce REST calls against a recorded cassette, diff the composed reply text) and uses the same `sandbox_runs.metrics` JSONB column for the additions. The pass gate in V0.3 is **intent-level safety**, not **answer-quality assurance** — Telegram approve+canary is the second line of defence for the answer-quality dimension.

## How Phase 6 talks to Phase 8

After Phase 6 writes `sandbox_runs` with `status='passed'`:

1. UPDATE `improvement_candidates.status` from `approved` → `sandbox_verified`
2. Write `events.candidate_status_changed`
3. Phase 7 watches `status='sandbox_verified'` candidates and emits patches
4. Phase 8 watches `status='patch_emitted'` candidates and starts canary deploy

If `failed`:
1. UPDATE candidate → `sandbox_failed`
2. Write `events.candidate_status_changed` with `to_status=sandbox_failed` and `fail_reason`
3. Dispatcher (Phase 4) on next Telegram interaction can show this in the 🔍 view-sandbox button

## 1000-case sim mode

Round 13-14 will run `op_assistant_sandbox_seed.py` which:

1. Creates `op_assistant_sandbox_kernel` if not exists, applies POSTGRES_SCHEMA + sandbox_runs DDL.
2. Loads 80-120 gemma4-seeded phrasing templates (run once, cached to `scripts/op_assistant/sandbox_seed_corpus.json`).
3. Python expander fills 1000 inbound rows deterministically with a single seed argument.
4. For each row, simulates the full Phase 2 → 3 → 4 → 6 → 7 → 8 pipeline using a fake Telegram client (records would-be approve/reject decisions to `events.sandbox_telegram_action`).
5. Writes one `sandbox_runs` row per candidate processed; aggregates the five KPIs from `round-06.md` Q4.

## DB self-maintenance scripts (Gary mandate)

Round 15 adds cron-scheduled scripts that keep both DBs healthy:

| script | what it does | schedule |
|---|---|---|
| `op_assistant_retention_cleanup.py` | already shipped — events 30d prune | daily 04:00 |
| `op_assistant_sandbox_purge.py` | drop `sandbox_runs` older than 7d (sandbox DB only) | daily 04:30 |
| `op_assistant_candidate_dedupe.py` | finds `(typed_payload, proposal_type)` pairs with >1 candidate where the older one is `applied`; marks the newer one as `superseded` (new status, additive enum) | weekly Sun 04:00 |
| `op_assistant_failed_replay_compaction.py` | for `sandbox_runs.status='failed'` >30d, archives `metrics` to a single summary row and drops the per-run rows | monthly 1st 04:00 |

These are intentionally separate small scripts (Karpathy 3 surgical) so each can be tuned / disabled independently.
