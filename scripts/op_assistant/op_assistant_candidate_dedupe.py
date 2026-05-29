"""V0.3 Round 12 — DB self-maintenance: dedupe candidates.

Looks for ``(typed_payload, proposal_type)`` pairs in the production
``improvement_candidates`` table where an earlier row already reached
``applied`` and a later row repeats it (gemma4 sometimes re-proposes a
keyword we've already shipped). Marks the later duplicates with
``superseded`` so they don't clutter Phase 4 / Phase 6 work and Gary
doesn't see "approve this again" in tomorrow's Telegram push.

The existing CHECK constraint on ``status`` predates V0.3; the SQL
below tolerates failure of an ALTER TABLE if the status enum doesn't
yet include 'superseded' — in that case we fall back to leaving a
note in events and not touching the row.

Cron::

    0 4 * * 0  /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
                scripts/op_assistant/op_assistant_candidate_dedupe.py
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


SUPERSEDED_STATUS = "superseded"


def find_duplicates(store: KernelStore) -> list[dict]:
    """Return rows where another applied candidate with the same
    typed_payload + proposal_type already exists and was created
    earlier. ``id`` is the newer row that should be marked superseded.
    """
    return store.fetch_all(
        "WITH applied AS ("
        "  SELECT id::text AS id, proposal_type, typed_payload, created_at "
        "  FROM improvement_candidates "
        "  WHERE status = 'applied' AND proposal_type IS NOT NULL"
        "), candidates AS ("
        "  SELECT id::text AS id, proposal_type, typed_payload, status, created_at "
        "  FROM improvement_candidates "
        "  WHERE status IN ('draft', 'approved', 'sandbox_verified', 'patch_emitted') "
        "  AND proposal_type IS NOT NULL"
        ") "
        "SELECT c.id, c.proposal_type, a.id AS earlier_applied_id "
        "FROM candidates c JOIN applied a "
        "  ON c.proposal_type = a.proposal_type "
        " AND c.typed_payload = a.typed_payload "
        " AND c.created_at > a.created_at"
    )


def dedupe(target_db_url: str) -> dict:
    store = KernelStore.from_url(target_db_url)
    marked = 0
    failed_constraint = 0
    try:
        duplicates = find_duplicates(store)
        now_iso = datetime.now(timezone.utc).isoformat()
        for dup in duplicates:
            try:
                with store.transaction() as tx:
                    tx.execute(
                        "UPDATE improvement_candidates "
                        "SET status = ? WHERE id = ?",
                        [SUPERSEDED_STATUS, dup["id"]],
                    )
                    tx.execute(
                        "INSERT INTO events (id, event_type, payload, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        [
                            str(uuid.uuid4()),
                            "candidate_status_changed",
                            json_param({
                                "candidate_id": dup["id"],
                                "to_status": SUPERSEDED_STATUS,
                                "by_phase": "candidate_dedupe_cron",
                                "by_actor": "system",
                                "earlier_applied_id": dup["earlier_applied_id"],
                            }),
                            now_iso,
                        ],
                    )
                marked += 1
            except Exception as exc:
                # Status CHECK constraint may not include 'superseded' yet.
                store.execute(
                    "INSERT INTO events (id, event_type, payload, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        str(uuid.uuid4()),
                        "candidate_dedupe_skipped",
                        json_param({
                            "candidate_id": dup["id"],
                            "earlier_applied_id": dup["earlier_applied_id"],
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                        }),
                        now_iso,
                    ],
                )
                failed_constraint += 1
    finally:
        store.close()
    return {
        "duplicates_found": len(duplicates),
        "marked_superseded": marked,
        "skipped_constraint": failed_constraint,
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
    parser.add_argument("--target-db", default=None)
    args = parser.parse_args()
    target = args.target_db or os.environ["KERNEL_DATABASE_URL"]
    out = dedupe(target)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
