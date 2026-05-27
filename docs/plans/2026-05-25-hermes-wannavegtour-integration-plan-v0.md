# Plan: Hermes Agent ↔ wannavegtour OP Bot Integration (v0 draft)

**Author**: drafted by Claude on 2026-05-25, for CEO-mode review by Gary.
**Status**: DRAFT — not approved. To be reviewed via `/plan-ceo-review`.
**Cross-refs**:
- `X_JsIHUfUjc-transcript.txt` (YC AI Native Company talk)
- `docs/hermes-integration-assessment-v0.md`
- `docs/hermes-agent-first-architecture.md`
- `docs/agent-profile-registry-v0.md`
- `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md`
- `spec/code-is-law-v0.md`, `spec/closed-loop-kernel-v0.md`

---

## The Question

The wannavegtour OP bot (v1) is **live on DGX Spark**: standalone Python stdlib HTTP listener, takes LINE webhooks, queries WooCommerce, replies in Traditional Chinese. Routing is deterministic ("code is rule"). Audit goes to local JSONL.

Hermes runtime also lives on DGX Spark (`~/.hermes/hermes-agent/`), already running for other clients. It provides: gateway, profiles, kanban, skills, sessions, tool dispatch.

**Should the wannavegtour OP bot become a Hermes-integrated agent (v2), and if so, how?**

This plan proposes a specific shape. It's the starting point for review, not the answer.

---

## Premises (challenge these)

1. **The bot is already in production.** Any rewrite must keep it serving OP traffic with no observable downtime (LINE retries help, but visible delays cost trust).
2. **"Code is rule" is non-negotiable.** Routing/dispatch stays deterministic Python. LLM may appear only in content generation (e.g. polishing a reply once the route is decided).
3. **Closed-loop kernel is the destination for events.** Per AI Native Company architecture, every business event must land in append-only PostgreSQL, not JSONL.
4. **Hermes profile is identity + state isolation, NOT a security sandbox.** Tool permissions must be enumerated explicitly.
5. **Multi-tenant is real.** wannavegtour is one of 8+ active customers in Hermes. Cross-tenant data must not bleed.
6. **DGX Spark is the single deployment box for now.** No distributed runtime concerns yet.

---

## Proposed Plan (v0)

### Phase 0: Decide v1-stays-as-is OR v2-rewrite (CEO call)

The two architectures cannot coexist on one LINE channel. Pick one before touching code.

- **v1 (status quo)**: standalone listener, JSONL audit, no closed-loop, no shared Hermes resources.
  - Pros: shipped, working, deterministic, simple.
  - Cons: violates "everything recorded" (JSONL ≠ Postgres append-only), no self-healing loop, can't share Company Brain with other Hermes profiles.
- **v2 (Hermes-integrated)**: LINE webhook routed through Hermes; reuses profile/kanban/skills; events flow into closed-loop kernel.
  - Pros: full audit, closed-loop ready, multi-tenant aware, shares improvements across customers.
  - Cons: rewrite cost, more moving parts, need to design handoff contracts.

**Default recommendation**: **v2, but phased** — keep v1 listener accepting webhooks for HTTP-200 latency, but tee every event into Hermes kanban + closed-loop kernel in parallel. After 2–4 weeks of parallel running, if v2 is stable, switch v1 to a dumb proxy and move all logic to Hermes profile.

### Phase 1: Read-only event ingestion (2–4 weeks, low risk)

Without changing reply behavior:

1. **Add tee in `wannavegtour.line_router`**: after every dispatch decision, write a structured event to:
   - Existing JSONL (unchanged, keep for debug)
   - Hermes kanban as a card on a `wannavegtour-line-events` board
   - Closed-loop kernel `events` table (with tenant=`wannavegtour`, source=`line`, intent classification, source_refs, content_hash)
2. **Register `wannavegtour-line-gateway` profile** in Hermes (per `docs/agent-profile-registry-v0.md` schema):
   - readable_inputs: LINE webhook payloads (scrubbed)
   - writable_outputs: kanban cards, kernel event rows
   - role: gateway (ephemeral, doesn't generate content)
   - sensitivity: customer-data, retention 365 days
3. **Wire secret scanning**: any outbound content (the reply text) passes through Hermes secret-scan before LINE reply API.
4. **Verify**: every LINE event in the wild produces (a) JSONL line, (b) kanban card, (c) kernel event row. Hash matches across all three.

### Phase 2: Profile-based reply pipeline (4–8 weeks)

After Phase 1 stable, move reply generation into Hermes:

1. **Register `wannavegtour-op-responder` profile** (durable):
   - state.db tracks: per-OP-user context, recent queries, cooldowns
   - skills: `availability_lookup`, `historical_lookup`, `help`
   - tool permissions: WooCommerce REST (read-only), LINE reply API, kanban update
2. **Router logic moves out of `line_router.py` into Hermes profile dispatcher** — but the deterministic regex parser (`query_parser.py`) stays as a skill. Code is still rule; rules now live in a registered skill.
3. **v1 listener becomes a thin proxy**: receives webhook, signature-verifies, drops into kanban, returns HTTP 200. Hermes profile picks it up async and replies via LINE push API.
4. **Verify**: reply latency p95 ≤ 2s (currently ~213ms for help command; budget for kanban hop adds maybe ~200ms). If p95 > 5s, rollback.

### Phase 3: Closed-loop activation (8–16 weeks)

Once reply pipeline is on Hermes:

1. **Failure detection**: kernel `failures` table watches for: WC API errors, signature failures, OP user complaints ("怎麼答錯了"), repeated unanswered queries.
2. **Improvement candidates**: when a query type repeats with no good answer, kernel proposes a candidate (e.g. extend `query_parser.py` regex, add a new skill, surface to OP team via kanban).
3. **Sandbox replay**: candidate runs against last N days of LINE events in sandbox; only promotes if no regressions.
4. **Human approval**: candidate appears as kanban card with diff + replay results; Gary approves → applies to production profile.
5. **Verify**: at least one self-healed query type by week 16. If zero, the loop isn't fed enough signal — re-check Phase 1 instrumentation.

---

## What This Plan Doesn't Cover (CEO should challenge)

- **Type 2 (WC write) worker**: still deferred. Plan assumes read-only forever. Maybe wrong — should write be part of v2?
- **Other LINE OP bots**: other customers may want the same pattern. Is `wannavegtour-line-gateway` reusable as `<tenant>-line-gateway` from day 1?
- **Company Brain integration**: not in this plan. OP queries are real customer-knowledge gold; should they flow into a queryable brain (e.g. Notion-replaced semantic store)?
- **Failure modes I haven't modeled**: kanban backlog, kernel DB down, secret-scan false positive blocking a legitimate reply.
- **The "v1 stays" minority case**: if v2 isn't worth the cost, what's the cheapest path to satisfy "events recorded in kernel" without full rewrite?
- **No tests, no rollback drill**: Phase 1 says "verify" but doesn't say what test harness produces it.

---

## Success Criteria (concrete, falsifiable)

- **Phase 1 done** when: 7 consecutive days, every LINE event appears in JSONL + kanban + kernel with matching content_hash, zero divergence.
- **Phase 2 done** when: reply latency p95 ≤ 2s for 14 days; manual rollback drill succeeds in < 5min.
- **Phase 3 done** when: at least one improvement_candidate has been auto-proposed, replayed, approved, and applied to production, with measurable reduction in the originating failure rate.

---

## Open Questions for Gary

1. v1-vs-v2 — commit to v2 phased, or stay v1 longer?
2. Is `wannavegtour` the right pilot tenant for the full Hermes ↔ kernel integration, or should Daguantech go first per `hermes-integration-assessment-v0.md` Path A?
3. Is "code is rule" preserved if rules live in Hermes-registered skills instead of `wannavegtour/` package?
4. Reply latency budget — 2s OK, or must stay sub-500ms?
5. Approval bottleneck — when self-healing proposes a fix, who approves? Just Gary, or can it be a designated OP person for low-risk changes?
