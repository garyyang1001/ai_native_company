"""V0.3 Round 12 — sandbox DB self-maintenance: purge old runs.

Drops sandbox_runs rows older than ``--retention-days`` (default 7) in
the sandbox DB only. Sandbox runs accumulate fast (one per sim
iteration + every approved candidate in production), so a short
retention window keeps the table cheap to query.

Production sandbox_runs are kept untouched — they're the audit trail
for every "Gary approved this candidate and the lab said it was safe"
decision and follow the kernel-wide 30-day events policy.

Cron::

    0 4 * * *  /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
                scripts/op_assistant/op_assistant_sandbox_purge.py
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


def purge(target_db_url: str, *, retention_days: int = 7) -> dict:
    store = KernelStore.from_url(target_db_url)
    try:
        before = store.scalar("SELECT COUNT(*) FROM sandbox_runs")
        store.execute(
            f"DELETE FROM sandbox_runs WHERE created_at < "
            f"NOW() - INTERVAL '{retention_days} days'"
        )
        after = store.scalar("SELECT COUNT(*) FROM sandbox_runs")
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "sandbox_runs_purge",
                json_param({
                    "retention_days": retention_days,
                    "rows_before": before,
                    "rows_after": after,
                    "rows_deleted": (before or 0) - (after or 0),
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
    finally:
        store.close()
    return {
        "retention_days": retention_days,
        "rows_before": before,
        "rows_after": after,
        "rows_deleted": (before or 0) - (after or 0),
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
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--target-db", default=None)
    args = parser.parse_args()
    if args.target_db:
        target = args.target_db
    else:
        target = os.environ["KERNEL_DATABASE_URL"].replace(
            "op_assistant_kernel", "op_assistant_sandbox_kernel",
        )
    out = purge(target, retention_days=args.retention_days)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
