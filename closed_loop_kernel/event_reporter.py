"""
EventReporter — 把 HermesRuntime 風格的 kanban.db（SQLite）內事件流，
單向同步到 Gary kernel 的 PostgreSQL（events / attempts / failures / lifecycle）。

設計重點：
  1. 唯讀開啟 kanban.db（`?mode=ro&immutable=1`），絕不寫回 HermesRuntime
  2. 增量同步：用 task_events.id 做 checkpoint，存在 kernel 的 events 表
  3. 冪等：用 task_events.id / task_runs.id 在 kernel 端去重
  4. 容錯：單筆 row 解析失敗只 log + skip，不中斷整個 sync 批次
  5. kanban.db 整個讀不到 → raise KanbanUnavailable，呼叫端決定要不要重試

對映規則寫在 docs/ohya-integration-v0.md 階段 2.5。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .store import KernelStore, json_param


CHECKPOINT_EVENT_TYPE = "kanban_sync_checkpoint"
KANBAN_EVENT_PREFIX = "ohya_kanban_"

# task_runs.outcome → Gary kernel failures.failure_type
_OUTCOME_TO_FAILURE_TYPE = {
    "crashed": "crash",
    "timed_out": "timeout",
    "spawn_failed": "spawn_failed",
    "gave_up": "gave_up",
    "failed": "failed",
}
_FAILED_OUTCOMES = set(_OUTCOME_TO_FAILURE_TYPE.keys())
_SUCCESS_OUTCOMES = {"completed"}


class KanbanUnavailable(Exception):
    """Raised when kanban.db cannot be opened or queried at all."""


@dataclass
class SyncResult:
    events_imported: int = 0
    attempts_imported: int = 0
    failures_opened: int = 0
    last_event_id: int = 0
    last_run_id: int = 0
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)


class EventReporter:
    def __init__(
        self,
        kanban_db_path: str,
        kernel_url: str,
        tenant_default: str = "ohya",
    ):
        self.kanban_db_path = kanban_db_path
        self.kernel_url = kernel_url
        self.tenant_default = tenant_default

    def sync(self) -> SyncResult:
        kanban = self._open_kanban_readonly()
        try:
            store = KernelStore.from_url(self.kernel_url)
            try:
                checkpoint = self._read_checkpoint(store)
                result = SyncResult(
                    last_event_id=checkpoint["last_event_id"],
                    last_run_id=checkpoint["last_run_id"],
                )

                self._import_task_events(kanban, store, result)
                self._import_task_runs(kanban, store, result)

                self._write_checkpoint(store, result.last_event_id, result.last_run_id)
                return result
            finally:
                store.close()
        finally:
            kanban.close()

    def _open_kanban_readonly(self) -> sqlite3.Connection:
        try:
            uri = f"file:{self.kanban_db_path}?mode=ro&immutable=1"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as exc:
            raise KanbanUnavailable(f"cannot open {self.kanban_db_path}: {exc}") from exc

    def _read_checkpoint(self, store: KernelStore) -> dict[str, int]:
        row = store.fetch_one(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY created_at DESC LIMIT 1",
            [CHECKPOINT_EVENT_TYPE],
        )
        if not row:
            return {"last_event_id": 0, "last_run_id": 0}
        try:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return {
                "last_event_id": int(payload.get("last_event_id", 0)),
                "last_run_id": int(payload.get("last_run_id", 0)),
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"last_event_id": 0, "last_run_id": 0}

    def _write_checkpoint(self, store: KernelStore, last_event_id: int, last_run_id: int) -> None:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                CHECKPOINT_EVENT_TYPE,
                json_param({"last_event_id": last_event_id, "last_run_id": last_run_id}),
                _now(),
            ],
        )

    def _import_task_events(
        self,
        kanban: sqlite3.Connection,
        store: KernelStore,
        result: SyncResult,
    ) -> None:
        try:
            cur = kanban.execute(
                """
                SELECT te.id, te.task_id, te.run_id, te.kind, te.payload, te.created_at,
                       t.tenant
                FROM task_events te
                LEFT JOIN tasks t ON t.id = te.task_id
                WHERE te.id > ?
                ORDER BY te.id ASC
                """,
                (result.last_event_id,),
            )
        except sqlite3.DatabaseError as exc:
            # kanban.db 可能部分損毀；整段事件流跳過，但 task_runs 部分仍嘗試
            result.skipped_rows.append({"table": "task_events", "error": f"query failed: {exc}"})
            return

        for raw in cur:
            try:
                row = dict(raw)
                tenant = row.get("tenant") or self.tenant_default
                event_payload = _safe_json_parse(row.get("payload"))
                event_payload["tenant"] = tenant
                event_payload["kanban_task_id"] = row["task_id"]
                event_payload["kanban_run_id"] = row.get("run_id")
                event_payload["kanban_event_id"] = row["id"]

                store.execute(
                    "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                    [
                        str(uuid.uuid4()),
                        f"{KANBAN_EVENT_PREFIX}{row['kind']}",
                        json_param(event_payload),
                        _from_unix(row["created_at"]),
                    ],
                )
                result.events_imported += 1
                if row["id"] > result.last_event_id:
                    result.last_event_id = row["id"]
            except Exception as exc:
                result.skipped_rows.append(
                    {"table": "task_events", "id": raw["id"] if "id" in raw.keys() else None, "error": str(exc)}
                )

    def _import_task_runs(
        self,
        kanban: sqlite3.Connection,
        store: KernelStore,
        result: SyncResult,
    ) -> None:
        try:
            cur = kanban.execute(
                """
                SELECT tr.id, tr.task_id, tr.profile, tr.status, tr.outcome,
                       tr.started_at, tr.ended_at, tr.error, tr.summary, tr.metadata,
                       t.title, t.tenant
                FROM task_runs tr
                LEFT JOIN tasks t ON t.id = tr.task_id
                WHERE tr.id > ? AND tr.ended_at IS NOT NULL
                ORDER BY tr.id ASC
                """,
                (result.last_run_id,),
            )
        except sqlite3.DatabaseError as exc:
            # 已知 OHYA kanban.db 此區段可能損毀；記下 skip
            result.skipped_rows.append({"table": "task_runs", "error": f"query failed: {exc}"})
            return

        for raw in cur:
            try:
                row = dict(raw)
                tenant = row.get("tenant") or self.tenant_default
                self._write_attempt_and_optional_failure(store, row, tenant, result)
                if row["id"] > result.last_run_id:
                    result.last_run_id = row["id"]
            except Exception as exc:
                result.skipped_rows.append(
                    {"table": "task_runs", "id": raw["id"] if "id" in raw.keys() else None, "error": str(exc)}
                )

    def _write_attempt_and_optional_failure(
        self,
        store: KernelStore,
        row: dict[str, Any],
        tenant: str,
        result: SyncResult,
    ) -> None:
        kanban_run_id = row["id"]
        kanban_task_id = row["task_id"]
        outcome = (row.get("outcome") or row.get("status") or "").lower()
        is_failure = outcome in _FAILED_OUTCOMES
        kernel_status = "failed" if is_failure else "success"

        attempt_id = _deterministic_uuid(f"ohya:run:{kanban_run_id}")
        input_payload = {
            "tenant": tenant,
            "kanban_task_id": kanban_task_id,
            "kanban_run_id": kanban_run_id,
            "title": row.get("title"),
            "profile": row.get("profile"),
        }
        output_payload = None
        if not is_failure:
            output_payload = {
                "summary": row.get("summary"),
                "metadata": _safe_json_parse(row.get("metadata")),
            }
        error_message = row.get("error") if is_failure else None

        # 避免重複（idempotent）：若 attempts 已有同 id 就 skip
        existing = store.fetch_one("SELECT id FROM attempts WHERE id = ?", [attempt_id])
        if existing:
            return

        with store.transaction() as conn:
            now = _now()
            # 寫 lifecycle 跟 attempt 一起
            conn.execute(
                """
                INSERT INTO attempt_lifecycle_events (id, attempt_id, state, metadata, created_at)
                VALUES (?, ?, 'started', ?, ?)
                """,
                [str(uuid.uuid4()), attempt_id, json_param({"source": "kanban_sync"}), _from_unix(row["started_at"])],
            )
            conn.execute(
                """
                INSERT INTO attempts (id, status, input, output, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    attempt_id,
                    kernel_status,
                    json_param(input_payload),
                    json_param(output_payload) if output_payload is not None else None,
                    error_message,
                    _from_unix(row["ended_at"]) or now,
                ],
            )
            if row.get("profile"):
                conn.execute(
                    """
                    INSERT INTO tool_calls (id, attempt_id, tool_name, arguments, result, status, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        attempt_id,
                        row["profile"],
                        json_param({"kanban_task_id": kanban_task_id, "kanban_run_id": kanban_run_id}),
                        json_param({"outcome": outcome, "summary": row.get("summary")}),
                        "failed" if is_failure else "success",
                        error_message,
                        _from_unix(row["ended_at"]) or now,
                    ],
                )
            conn.execute(
                """
                INSERT INTO attempt_lifecycle_events (id, attempt_id, state, metadata, created_at)
                VALUES (?, ?, 'finished', ?, ?)
                """,
                [str(uuid.uuid4()), attempt_id, json_param({"status": kernel_status, "source": "kanban_sync"}), _from_unix(row["ended_at"]) or now],
            )
            if is_failure:
                failure_type = _OUTCOME_TO_FAILURE_TYPE.get(outcome, "unknown")
                conn.execute(
                    """
                    INSERT INTO failures (id, attempt_id, failure_type, context, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        attempt_id,
                        failure_type,
                        json_param({
                            "tenant": tenant,
                            "kanban_task_id": kanban_task_id,
                            "kanban_run_id": kanban_run_id,
                            "profile": row.get("profile"),
                            "error": error_message,
                            "summary": row.get("summary"),
                        }),
                        _from_unix(row["ended_at"]) or now,
                    ],
                )
                result.failures_opened += 1
        result.attempts_imported += 1


def _safe_json_parse(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _from_unix(value: Any) -> str:
    if value is None:
        return _now()
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            # kanban 用 ms 還是 seconds 不一定；> 10^12 視為 ms
            if ts > 1_000_000_000_000:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        if isinstance(value, str):
            return value
    except (ValueError, OverflowError, OSError):
        pass
    return _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deterministic_uuid(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))
