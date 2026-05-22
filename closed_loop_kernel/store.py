from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


class KernelStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()

    @classmethod
    def in_memory(cls) -> "KernelStore":
        return cls(sqlite3.connect(":memory:", check_same_thread=False))

    @classmethod
    def from_path(cls, path: str | Path) -> "KernelStore":
        return cls(sqlite3.connect(str(path), check_same_thread=False))

    def initialize(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA_SQL)
            self.conn.commit()

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> None:
        with self._lock:
            self.conn.execute(sql, tuple(params or ()))
            self.conn.commit()

    def fetch_all(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(sql, tuple(params or ())).fetchall()
        return [dict(row) for row in rows]

    def fetch_one(self, sql: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params or ())).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, params: Iterable[Any] | None = None) -> Any:
        with self._lock:
            row = self.conn.execute(sql, tuple(params or ())).fetchone()
        return row[0] if row else None

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self.conn.execute("BEGIN")
                yield self.conn
            except Exception:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS policy_gates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    rule_definition TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt_lifecycle_events (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('started', 'running', 'finished')),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    event_id TEXT REFERENCES events(id),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    input TEXT NOT NULL,
    output TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id),
    gate_id TEXT REFERENCES policy_gates(id),
    decision_maker TEXT NOT NULL,
    action_taken TEXT NOT NULL CHECK (action_taken IN ('allowed', 'blocked', 'approval_requested')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id),
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    result TEXT,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failures (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id),
    failure_type TEXT NOT NULL,
    context TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'analyzing', 'proposed', 'resolved', 'ignored')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS improvement_candidates (
    id TEXT PRIMARY KEY,
    failure_id TEXT NOT NULL REFERENCES failures(id),
    target_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    target_artifact_name TEXT NOT NULL,
    target_artifact_type TEXT NOT NULL,
    target_artifact_version INTEGER NOT NULL,
    base_artifact_hash TEXT NOT NULL,
    patch_type TEXT NOT NULL,
    proposed_content TEXT NOT NULL,
    validation_assertions TEXT NOT NULL,
    rollback_plan TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'sandbox_verified', 'approved', 'rejected', 'applied')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replays (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES improvement_candidates(id),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    validation_results TEXT NOT NULL,
    sandbox_schema TEXT,
    sandbox_env TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES improvement_candidates(id),
    approved_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    comments TEXT,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempt_lifecycle_no_update
BEFORE UPDATE ON attempt_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'attempt_lifecycle_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempt_lifecycle_no_delete
BEFORE DELETE ON attempt_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'attempt_lifecycle_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempts_no_update
BEFORE UPDATE ON attempts
BEGIN
    SELECT RAISE(ABORT, 'attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempts_no_delete
BEFORE DELETE ON attempts
BEGIN
    SELECT RAISE(ABORT, 'attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_tool_calls_no_update
BEFORE UPDATE ON tool_calls
BEGIN
    SELECT RAISE(ABORT, 'tool_calls is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_tool_calls_no_delete
BEFORE DELETE ON tool_calls
BEGIN
    SELECT RAISE(ABORT, 'tool_calls is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_decisions_no_update
BEFORE UPDATE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_decisions_no_delete
BEFORE DELETE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_approvals_no_update
BEFORE UPDATE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_approvals_no_delete
BEFORE DELETE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals is append-only');
END;
"""
