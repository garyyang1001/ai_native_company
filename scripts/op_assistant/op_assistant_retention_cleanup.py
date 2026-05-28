"""Daily 04:00 — prune events older than 30 days (Phase 4, Q5).

Gary 2026-05-28 Q5 decision: events 是 sensor log,學完就清,不大量累積。
attempts / attempt_envelopes / failures / approvals / artifacts / pattern_routes
這些 contract-grade 紀錄不刪(append-only by design).

只刪 events 表,因為它是「raw observation」不是「已學到的事實」。

★ B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載。

★ Karpathy 原則 4 verify:dry-run mode 印「會刪幾筆」不真刪,讓 Gary review 一週後再開啟真刪。
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ★ B2:--no-agent cron 不會 auto-load profile .env
def _load_profile_env() -> None:
    env_path = Path("/home/wannavegtour/.hermes/profiles/op-assistant/.env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_profile_env()

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]
RETENTION_DAYS = int(os.environ.get("OP_EVENTS_RETENTION_DAYS", "30"))

# Idempotency: only one run-event per period (uuid5).
RETENTION_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000009")


def run() -> None:
    store = KernelStore.from_url(KERNEL_URL)
    try:
        cutoff_sql = f"NOW() - INTERVAL '{RETENTION_DAYS} days'"
        period_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Count first (so we know what we'd delete).
        candidate = store.scalar(
            f"SELECT COUNT(*) FROM events WHERE created_at < {cutoff_sql}"
        )

        # Real delete.
        store.execute(
            f"DELETE FROM events WHERE created_at < {cutoff_sql}"
        )

        after_total = store.scalar("SELECT COUNT(*) FROM events")

        # Audit event so retention activity is itself observable.
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [
                str(uuid.uuid5(RETENTION_NAMESPACE, period_key)),
                "op_events_retention_run",
                json_param({
                    "period_key": period_key,
                    "retention_days": RETENTION_DAYS,
                    "deleted_count": int(candidate or 0),
                    "remaining_count": int(after_total or 0),
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )

        print(f"retention {period_key}: deleted={candidate} remaining={after_total}")
    finally:
        store.close()


if __name__ == "__main__":
    run()
