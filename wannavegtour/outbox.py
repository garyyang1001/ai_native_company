"""SQLite retry buffer for kernel writes.

This is a transport outbox, not company memory and not source of truth.
See docs/plans/2026-05-28-learning-loop-design-v0.2.md Q4 lock — no daemon,
only enqueue + flush_once + idempotency.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


class KernelOutbox:
    def __init__(self, sqlite_path: str):
        self.sqlite_path = sqlite_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.sqlite_path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS kernel_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    profile_id TEXT,
                    task_id TEXT,
                    run_id TEXT,
                    record_type TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    sensitivity_level TEXT NOT NULL,
                    retention_policy TEXT NOT NULL,
                    source_ref_hash TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    last_error TEXT,
                    kernel_ack_id TEXT,
                    acked_at TEXT,
                    expires_at TEXT
                )
                """
            )

    def enqueue(self, record_type: str, payload: dict, idempotency_key: str) -> str:
        payload_json = _payload_json(payload)
        now = _now()
        outbox_id = str(uuid.uuid4())

        with self._connect() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO kernel_outbox (
                    outbox_id, created_at, updated_at,
                    profile_id, task_id, run_id,
                    record_type, contract_version,
                    payload_json, payload_hash,
                    sensitivity_level, retention_policy, source_ref_hash,
                    idempotency_key, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    outbox_id,
                    now,
                    now,
                    payload.get("profile_id"),
                    payload.get("task_id"),
                    payload.get("run_id"),
                    record_type,
                    payload.get("contract_version", "v0"),
                    payload_json,
                    _payload_hash(payload_json),
                    payload.get("sensitivity_level", "confidential"),
                    payload.get("retention_policy", "30d"),
                    payload.get("source_ref_hash"),
                    idempotency_key,
                ),
            )
            row = con.execute(
                "SELECT outbox_id FROM kernel_outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return str(row[0])

    def flush_once(self, writer: Callable[[dict], str]) -> tuple[int, int]:
        now = _now()
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT outbox_id, payload_json
                FROM kernel_outbox
                WHERE status = 'pending'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at
                """,
                (now,),
            ).fetchall()

        success_count = 0
        fail_count = 0

        for outbox_id, payload_json in rows:
            try:
                kernel_ack_id = writer(json.loads(payload_json))
            except Exception as exc:  # noqa: BLE001 - outbox must keep retrying writer errors.
                fail_count += 1
                next_retry_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=60)
                ).isoformat()
                with self._connect() as con:
                    con.execute(
                        """
                        UPDATE kernel_outbox
                        SET updated_at = ?, attempt_count = attempt_count + 1,
                            next_retry_at = ?, last_error = ?
                        WHERE outbox_id = ?
                        """,
                        (_now(), next_retry_at, str(exc), outbox_id),
                    )
                continue

            success_count += 1
            with self._connect() as con:
                con.execute(
                    """
                    UPDATE kernel_outbox
                    SET updated_at = ?, status = 'acked',
                        kernel_ack_id = ?, acked_at = ?
                    WHERE outbox_id = ?
                    """,
                    (_now(), kernel_ack_id, _now(), outbox_id),
                )

        return success_count, fail_count

    def pending_count(self) -> int:
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM kernel_outbox WHERE status = 'pending'"
            ).fetchone()
        return int(row[0])
