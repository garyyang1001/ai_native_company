"""V0.3 Round 12 — 1000-case sim runner against sandbox DB.

Drives daily_curate against the already-seeded sandbox database, then
runs Phase 6 sandbox_replay against every candidate it produced, and
aggregates the five KPIs from round-06.md Q4 plus a per-status
breakdown of the candidates.

Phase 7 (patch emitter) + Phase 8 (apply + service restart) are NOT
fired during the sim, because they would touch production source code
(`wannavegtour/query_parser.py`) and bounce the live bot service. The
sim stops at Phase 6 sandbox_runs and reports what *would* happen if
those candidates were approved + chained. That's the right thing to do
in a lab — it lets us measure proposal quality, gating effectiveness,
and false-positive rates without affecting production.

Usage::

    OP_PHASE2_DRY_RUN=     # leave unset; we want real candidates inserted
    /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
        scripts/op_assistant/op_assistant_sim_runner.py \\
        --target-db postgresql://.../op_assistant_sandbox_kernel \\
        [--max-candidates 50]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore  # noqa: E402


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_sim(*, target_db_url: str, max_candidates: int | None = None) -> dict[str, Any]:
    """Drive daily_curate + Phase 6 replay against the sandbox DB."""

    # ---- env setup -----
    os.environ["KERNEL_DATABASE_URL"] = target_db_url
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")     # silence Telegram push
    os.environ.setdefault("TELEGRAM_HOME_CHANNEL", "")
    os.environ.setdefault("OP_PHASE3_INLINE_KEYBOARD", "")

    scripts_dir = Path(REPO_PATH) / "scripts" / "op_assistant"

    # ---- daily_curate (writes candidates into sandbox DB) -----
    t_dc_start = time.monotonic()
    daily_curate = _load_module(
        scripts_dir / "op_assistant_daily_curate.py",
        "op_daily_curate_sim",
    )
    try:
        daily_curate.run()
    except Exception as exc:
        return {
            "phase": "daily_curate",
            "error": f"{type(exc).__name__}: {exc}",
        }
    dc_duration_ms = int((time.monotonic() - t_dc_start) * 1000)

    # ---- enumerate sandbox candidates -----
    store = KernelStore.from_url(target_db_url)
    try:
        candidates = store.fetch_all(
            "SELECT id::text AS id, status, proposal_type, typed_payload "
            "FROM improvement_candidates "
            "WHERE proposal_type IS NOT NULL "
            "ORDER BY created_at DESC"
        )
    finally:
        store.close()

    if max_candidates is not None:
        candidates = candidates[:max_candidates]

    # ---- sandbox replay each candidate -----
    sandbox_replay = _load_module(
        scripts_dir / "op_assistant_sandbox_replay.py",
        "op_sandbox_replay_sim",
    )

    replay_results: list[dict[str, Any]] = []
    t_replay_start = time.monotonic()
    for cand in candidates:
        try:
            r = sandbox_replay.run_sandbox_replay(
                candidate_id=cand["id"],
                target_db_url=target_db_url,
            )
        except Exception as exc:
            r = {
                "candidate_id": cand["id"],
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "metrics": {},
            }
        replay_results.append({
            "candidate_id": cand["id"],
            "proposal_type": cand["proposal_type"],
            "status": r.get("status"),
            "fail_reason": r.get("fail_reason"),
            "metrics": r.get("metrics", {}),
            "duration_ms": r.get("duration_ms"),
        })
    replay_duration_ms = int((time.monotonic() - t_replay_start) * 1000)

    # ---- aggregate KPI -----
    total = len(replay_results)
    passed = sum(1 for r in replay_results if r["status"] == "passed")
    failed = sum(1 for r in replay_results if r["status"] == "failed")
    errored = sum(1 for r in replay_results if r["status"] == "error")
    over_greedy_hits = sum(
        1 for r in replay_results
        if (r.get("metrics") or {}).get("over_greedy_rate", 0.0) >= 0.50
    )

    avg_replay_ms = (
        sum(r.get("duration_ms") or 0 for r in replay_results) / total
        if total > 0 else 0.0
    )

    return {
        "sandbox_db": target_db_url.split("@")[-1],
        "daily_curate_duration_ms": dc_duration_ms,
        "replay_duration_ms": replay_duration_ms,
        "candidate_total": total,
        "candidate_status": {
            "passed": passed,
            "failed": failed,
            "errored": errored,
        },
        "over_greedy_rate_at_50pct": over_greedy_hits,
        "avg_replay_ms": round(avg_replay_ms, 2),
        "kpi_v0_3_proxies": {
            # K1: daily push time — N/A in sim (no Telegram); proxy = daily_curate run time
            "K1_daily_curate_run_ms": dc_duration_ms,
            # K2: approve → applied — V0.3 simple chains automatically; proxy = avg replay+chain ms
            "K2_avg_chain_ms_proxy": round(avg_replay_ms, 2),
            # K3: false positive — proxy = over-greedy candidates (greedy rules that would still get gemma4-proposed)
            "K3_over_greedy_rate": round(over_greedy_hits / total, 4) if total else 0.0,
            # K4: auto-revert — V0.3 simple has no canary; proxy = sandbox replay failed rate
            "K4_replay_fail_rate": round(failed / total, 4) if total else 0.0,
            # K5: gemma4 approve / duplicate — single sim round, can't compute trend
            "K5_round_trend": "single_run_no_trend",
        },
        "sample_replay_results": replay_results[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-db", required=False, default=None)
    parser.add_argument("--max-candidates", type=int, default=None)
    args = parser.parse_args()

    if args.target_db:
        target = args.target_db
    else:
        prod = os.environ.get("KERNEL_DATABASE_URL")
        if not prod:
            print("KERNEL_DATABASE_URL not set; provide --target-db",
                  file=sys.stderr)
            return 2
        target = prod.replace(
            "op_assistant_kernel", "op_assistant_sandbox_kernel",
        )

    result = run_sim(target_db_url=target, max_candidates=args.max_candidates)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
