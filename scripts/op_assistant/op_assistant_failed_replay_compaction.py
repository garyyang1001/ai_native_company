"""V0.3 Round 12 — DB self-maintenance: compact old failed replays.

For ``sandbox_runs.status='failed'`` rows older than
``--retention-days`` (default 30), archives the ``metrics`` blob into a
single ``events.sandbox_runs_compacted`` summary row and drops the
per-run rows. Keeps the table query-fast without losing the
"this candidate failed this many times in the last quarter" signal.

Cron::

    0 4 1 * *  /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
                scripts/op_assistant/op_assistant_failed_replay_compaction.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402


def compact(target_db_url: str, *, retention_days: int = 30) -> dict:
    store = KernelStore.from_url(target_db_url)
    try:
        # Snapshot per-candidate failure counts before deletion.
        summaries = store.fetch_all(
            f"SELECT candidate_id::text AS candidate_id, "
            f"COUNT(*) AS failed_count, "
            f"MIN(created_at) AS first_failed_at, "
            f"MAX(created_at) AS last_failed_at, "
            f"array_agg(DISTINCT fail_reason) AS fail_reasons "
            f"FROM sandbox_runs "
            f"WHERE status = 'failed' "
            f"AND created_at < NOW() - INTERVAL '{retention_days} days' "
            f"GROUP BY candidate_id"
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        for s in summaries:
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    "sandbox_runs_compacted",
                    json_param({
                        "candidate_id": s["candidate_id"],
                        "failed_count": int(s["failed_count"] or 0),
                        "first_failed_at": s["first_failed_at"].isoformat()
                            if s["first_failed_at"] else None,
                        "last_failed_at": s["last_failed_at"].isoformat()
                            if s["last_failed_at"] else None,
                        "fail_reasons": [
                            r for r in (s["fail_reasons"] or []) if r
                        ],
                        "retention_days": retention_days,
                    }),
                    now_iso,
                ],
            )
        # Now drop the per-run rows.
        store.execute(
            f"DELETE FROM sandbox_runs "
            f"WHERE status = 'failed' "
            f"AND created_at < NOW() - INTERVAL '{retention_days} days'"
        )
    finally:
        store.close()
    return {
        "candidates_summarised": len(summaries),
        "total_failed_rows_compacted": sum(
            int(s["failed_count"] or 0) for s in summaries
        ),
        "retention_days": retention_days,
    }


def _load_env() -> None:
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    for path in [
        Path.home() / ".hermes" / "profiles" / profile / ".env",
        Path.home() / ".hermes" / ".env",
    ]:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(),
                                   val.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--target-db", default=None)
    args = parser.parse_args()
    target = args.target_db or os.environ["KERNEL_DATABASE_URL"]
    out = compact(target, retention_days=args.retention_days)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
