# OP Assistant V0.3 contracts

Round 7 (2026-05-29) lock-down per Round 6 codex xhigh architectural map; revised after Round 7 codex review caught four substantive design bugs (see §below).

This index plus **three contract files** are the immovable interfaces Phase 3-8 implementation rides on. Once locked, lab lane (Phase 6 → 7) and human-review lane (Phase 3 → 4 → 5) can ship in parallel without breaking each other.

## Files

This index file is not itself a contract; it carries cross-cutting rules and points to the three actual contracts below:

| Contract | Scope | Phases that consume |
|---|---|---|
| [`callback_data_v0.md`](callback_data_v0.md) | Telegram inline keyboard `callback_data` format (under 64 byte) + button taxonomy | 3, 4, 8 |
| [`approval_audit_v0.md`](approval_audit_v0.md) | `approvals` table schema delta + dispatcher transactional claim + reject UX | 4, 5 |
| [`sandbox_protocol_v0.md`](sandbox_protocol_v0.md) | sandbox DB (`op_assistant_sandbox_kernel`) layout + fake clock + PII anonymisation + `sandbox_runs` schema + 4 metric calculation | 6, 7, 8 |

## Cross-cutting rules

These apply to every contract and any Phase 3-8 implementation:

### Reviewer separation (Round 1 U35 + Round 6 New 2 + Round 7 codex sharpening)

The rule is **role-based**, not **table-based**. The same Telegram-approve transaction is allowed (and required) to write to `approvals` + `improvement_candidates` + `events` in one atomic step — that's how we avoid half-approved state. What we forbid is one actor playing more than one role.

The three roles:

- **Proposer**: produces a candidate improvement (a patch suggestion).
- **Approver**: makes the binding accept/reject decision.
- **Applier**: writes the patch to source code or production state.

No single actor (LLM, Python module, or human) may hold more than one role for the same candidate.

Concrete assignments for V0.3:

- `gemma4` (Phase 2 daily_curate) is a **Proposer**. It must not write `approvals` rows or touch `query_parser.py`.
- Gary (Telegram tap) is the only **Approver** in V0.3. The Phase 4 dispatcher translates his tap into the approval transaction; it has no decision-making code, just record-keeping.
- Phase 7 patch emitter is the **Applier**. It must not write `approvals` rows; it only writes git commits after `improvement_candidates.status = 'sandbox_verified'`.
- Sandbox replay (Phase 6) is a **verifier**, not an approver — it sets `sandbox_verified` / `sandbox_failed` status but never writes to `approvals`.
- Canary judge (Phase 8) is an **auto-reverter**, not an applier — it can `git revert` previously applied patches but cannot apply new ones.

The forbidden pattern is "the same agent both proposes the patch and approves it." That's why we never let `gemma4` write to `approvals`, and why Phase 4 dispatcher has no LLM in its decision path. Concentrating multi-table writes inside one Phase 4 transaction is fine; mixing roles across that transaction is not.

### Determinism (Code is Law principle)

- All `created_at` / `NOW()` calls inside sandbox runs go through a fake clock seeded from `sandbox_runs.clock_started_at`. PostgreSQL `NOW()` is only used in production paths.
- All UUIDs derived from `(seed, role)` use `uuid5` not `uuid4` so re-runs hash to the same id.
- All gemma4 calls in sandbox carry the `model_digest` (not just `"gemma4:e4b"`) so a future model upgrade is visible in `sandbox_runs.metrics`.

### Append-only audit (already in V0.2 contract §9)

- `approvals` and `attempts` stay append-only — re-approve, re-reject, or re-process always inserts a new row.
- `improvement_candidates.status` may be UPDATE'd, but every transition writes `events.candidate_status_changed`.

## Lock-down status

Once Gary signs off on this README + the three contract files, Round 8 onwards may treat these specs as canonical. Any later change must come back through a numbered iteration round and re-version the contract (`callback_data_v1.md`, etc.).
