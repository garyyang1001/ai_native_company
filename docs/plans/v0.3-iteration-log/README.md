# V0.3 iteration log

Round-by-round capture of the Claude ↔ codex xhigh design loop that turned `2026-05-28-op-assistant-v0.3-design.md` into per-phase implementation specs.

## Why this dir exists

Gary 2026-05-29 mandate: max 100 rounds of Claude (Opus 4.7 extended thinking) ↔ codex (`gpt-5.5` `model_reasoning_effort=xhigh`) iteration to collapse architectural unknowns into ship-ready Phase 2-8 specs. Plan B (karpathy-aligned): goal-driven per-phase ship rather than 100 rounds of pure design.

Gary chose "both" — process value (AI Native Company case study) **and** outcome (V0.3 production ship). This dir is the process artifact.

## Conventions

- One commit per round.
- File:`round-NN.md`,monotonic increasing.
- Each round records:
  - Starting state
  - Codex prompt path (in `.claude/jobs/`, not in repo)
  - Codex output summary
  - Decisions / spec changes
  - Karpathy lens reflection
  - Next round plan
- V0.3 doc (`docs/plans/2026-05-28-op-assistant-v0.3-design.md`) is patched at round-end when a batch of decisions is collapsed. Doc patches and round-NN.md may be the same commit if they map 1:1, separate commits otherwise.

## Stop conditions

- 100 rounds (hard ceiling)
- Two consecutive rounds with no new substantive finding
- Gary stops it

## Index

- [round-01.md](round-01.md) — initial enumeration (41 unknowns) + priority + Round 2 plan
- [round-02.md](round-02.md) — 8 條 p0 spec collapse (Claude 1 ✓ + 7 ✗ codex 反提案,全採納)
- [round-03.md](round-03.md) — R18 spike: production failures→inbound chain broken → Phase 2 U39 降階 substring fallback (R19 追蹤 V0.4 fix)
- [round-04.md](round-04.md) — Phase 2 simple 版 brief + codex conditional GO(加 type whitelist + uuid5 deterministic id)
- [round-05.md](round-05.md) — Phase 2 simple 版 SHIPPED production(schema migration / `_persist_candidates` / 11 tests pass / 2 candidates + 1 reject live;reject path idempotency bug caught + fixed mid-round)
- [round-06.md](round-06.md) — sandbox + Phase 3-8 + 1000 case 大架構諮詢 → codex Option A sandbox DB / LLM seed + Python expand / contracts-first parallel ship / 5 完美 KPI
- [round-07.md](round-07.md) — 4 contracts locked(codex 兩輪 review:Round 7 給 4 全 No-Go 我全收,Round 7.5 給 2 Go + 2 small SQL/wording fix 我全修)
