"""One-shot migration: add pattern_routes table to op-assistant-kernel.

Run once manually. Idempotent: uses CREATE TABLE IF NOT EXISTS.

Usage:
    .venv/bin/python scripts/op_assistant/migrate_add_pattern_routes.py
    .venv/bin/python scripts/op_assistant/migrate_add_pattern_routes.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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

from closed_loop_kernel.store import KernelStore

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]


def _validate_kernel_dsn(url: str) -> None:
    """Same DSN guard as ETL: refuse if not op-assistant-kernel."""
    expected = {"host": "127.0.0.1", "port": 5434, "db": "op_assistant_kernel", "user": "op_kernel"}
    parsed = urlparse(url)
    actual = {
        "host": parsed.hostname,
        "port": parsed.port,
        "db": parsed.path.lstrip("/"),
        "user": parsed.username,
    }
    if actual != expected:
        diff = {key: f"got={actual.get(key)!r} want={expected[key]!r}" for key in expected if actual.get(key) != expected[key]}
        raise RuntimeError(f"DSN mismatch; refusing to run migration. Diff: {diff}")


_validate_kernel_dsn(KERNEL_URL)

DDL = """
CREATE TABLE IF NOT EXISTS pattern_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_signature VARCHAR(255) NOT NULL,
    artifact_id UUID NOT NULL REFERENCES artifacts(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pattern_routes_active_unique
    ON pattern_routes (pattern_signature) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_pattern_routes_signature
    ON pattern_routes (pattern_signature) WHERE is_active = TRUE;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    store = KernelStore.from_url(KERNEL_URL)
    try:
        if args.dry_run:
            print("DRY RUN; would execute:")
            print(DDL)
            return
        for stmt in [statement.strip() for statement in DDL.split(";") if statement.strip()]:
            store.execute(stmt + ";")
        print("migration applied")

        row = store.fetch_one(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'pattern_routes'"
        )
        print(f"pattern_routes table exists: {bool(row['n'])}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
