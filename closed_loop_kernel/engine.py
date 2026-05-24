from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .store import KernelStore, _normalize_row, json_param


class SecurityError(Exception):
    pass


class _RaceCondition(Exception):
    """Internal sentinel raised inside apply transaction to trigger rollback + candidate→draft."""
    pass


class KernelEngine:
    def __init__(self, store: KernelStore):
        self.store = store

    def generate_id(self) -> str:
        return str(uuid.uuid4())

    def start_attempt(self, input_payload: dict[str, Any]) -> str:
        attempt_id = self.generate_id()
        self.record_lifecycle_event(attempt_id, "started", {"input": input_payload})
        self.record_lifecycle_event(attempt_id, "running")
        return attempt_id

    def record_lifecycle_event(
        self,
        attempt_id: str,
        state: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.store.execute(
            """
            INSERT INTO attempt_lifecycle_events (id, attempt_id, state, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [self.generate_id(), attempt_id, state, _json(metadata or {}), _now(created_at)],
        )

    def finish_attempt(
        self,
        attempt_id: str,
        status: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        decisions: list[dict[str, Any]] | None = None,
    ) -> None:
        if status not in {"success", "failed"}:
            raise ValueError("status must be success or failed")

        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO attempts (id, status, input, output, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [attempt_id, status, _json(input_payload), _json(output_payload) if output_payload is not None else None, error_message, _now()],
            )
            for call in tool_calls or []:
                conn.execute(
                    """
                    INSERT INTO tool_calls (id, attempt_id, tool_name, arguments, result, status, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        self.generate_id(),
                        attempt_id,
                        call["tool_name"],
                        _json(call.get("arguments", {})),
                        _json(call.get("result")) if "result" in call else None,
                        call.get("status", "success"),
                        call.get("error_message"),
                        _now(),
                    ],
                )
            for decision in decisions or []:
                conn.execute(
                    """
                    INSERT INTO decisions (id, attempt_id, gate_id, decision_maker, action_taken, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        self.generate_id(),
                        attempt_id,
                        decision.get("gate_id"),
                        decision["decision_maker"],
                        decision["action_taken"],
                        decision["reason"],
                        _now(),
                    ],
                )
            conn.execute(
                """
                INSERT INTO attempt_lifecycle_events (id, attempt_id, state, metadata, created_at)
                VALUES (?, ?, 'finished', ?, ?)
                """,
                [self.generate_id(), attempt_id, _json({"status": status}), _now()],
            )
            if status == "failed":
                conn.execute(
                    """
                    INSERT INTO failures (id, attempt_id, failure_type, context, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', ?)
                    """,
                    [
                        self.generate_id(),
                        attempt_id,
                        _failure_type(error_message),
                        _json({"error_message": error_message, "input": input_payload}),
                        _now(),
                    ],
                )

    def create_artifact(self, name: str, artifact_type: str, content: str) -> str:
        version = (self.store.scalar("SELECT MAX(version) FROM artifacts WHERE name = ?", [name]) or 0) + 1
        artifact_id = self.generate_id()
        self.store.execute(
            """
            INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, TRUE, ?)
            """,
            [artifact_id, name, artifact_type, content, _hash(content), version, _now()],
        )
        return artifact_id

    def create_failure_for_test(self, failure_type: str) -> str:
        attempt_id = self.start_attempt({"test": failure_type})
        self.finish_attempt(attempt_id, "failed", {"test": failure_type}, error_message=f"{failure_type}: test failure")
        return self.store.scalar("SELECT id FROM failures WHERE attempt_id = ?", [attempt_id])

    def propose_improvement(
        self,
        failure_id: str,
        target_artifact_id: str,
        patch_type: str,
        proposed_content: str,
        validation_assertions: dict[str, Any],
        rollback_plan: dict[str, Any],
    ) -> str:
        artifact = self.store.fetch_one("SELECT * FROM artifacts WHERE id = ?", [target_artifact_id])
        if not artifact:
            raise ValueError(f"artifact not found: {target_artifact_id}")
        candidate_id = self.generate_id()
        self.store.execute(
            """
            INSERT INTO improvement_candidates (
                id, failure_id, target_artifact_id, target_artifact_name, target_artifact_type,
                target_artifact_version, base_artifact_hash, patch_type, proposed_content,
                validation_assertions, rollback_plan, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """,
            [
                candidate_id,
                failure_id,
                target_artifact_id,
                artifact["name"],
                artifact["artifact_type"],
                artifact["version"],
                artifact["content_hash"],
                patch_type,
                proposed_content,
                _json(validation_assertions),
                _json(rollback_plan),
                _now(),
            ],
        )
        self.store.execute("UPDATE failures SET status = 'proposed' WHERE id = ?", [failure_id])
        return candidate_id

    def record_replay(
        self,
        candidate_id: str,
        status: str,
        validation_results: dict[str, Any],
        sandbox_schema: str | None = None,
        sandbox_env: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> str:
        replay_id = self.generate_id()
        self.store.execute(
            """
            INSERT INTO replays (id, candidate_id, status, validation_results, sandbox_schema, sandbox_env, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [replay_id, candidate_id, status, _json(validation_results), sandbox_schema, _json(sandbox_env or {}), error_message, _now()],
        )
        if status == "success":
            self.store.execute("UPDATE improvement_candidates SET status = 'sandbox_verified' WHERE id = ?", [candidate_id])
            self._record_event("approval_required", {"candidate_id": candidate_id})
        else:
            self.store.execute("UPDATE improvement_candidates SET status = 'draft' WHERE id = ?", [candidate_id])
        return replay_id

    def replay_sql_candidate(
        self,
        candidate_id: str,
        sandbox: "Any",
        setup_sql: str | None = None,
    ) -> str:
        """
        在 SqlSandbox 內 replay 一個 `sql_patch` candidate。

        流程：
          1. 讀 candidate，確認 patch_type 為 `sql_patch`；
          2. 對 proposed_content 過 SQL static lint 黑名單；
          3. 開臨時 schema；可選地以 admin 身份跑 setup_sql（seed/CREATE 表用）；
          4. 以 sandbox_runner 身份跑 proposed_content；
          5. 比對 validation_assertions（expected_row_count / expected_result）；
          6. 寫入 replays 並更新 candidate 狀態（成功 → sandbox_verified，失敗 → draft）。

        參數 `sandbox` 接受任何符合 SqlSandbox 介面（`temp_schema()` context manager
        + `run_as_runner(sql, schema)` method）的物件，以利測試替身。
        """
        candidate = self.store.fetch_one("SELECT * FROM improvement_candidates WHERE id = ?", [candidate_id])
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if candidate["patch_type"] != "sql_patch":
            raise ValueError("replay_sql_candidate only supports sql_patch candidates")

        # 只 lint 候選提供的 proposed_content；setup_sql 是引擎內部呼叫者傳入的
        # 信任輸入（例如為了在 temp schema 內建測試表 + 種 seed data），可能合法
        # 引用 public.* 以複製生產表結構，不適用 candidate lint。
        self.validate_sql_patch(candidate["proposed_content"])

        assertions = json.loads(candidate["validation_assertions"])

        with sandbox.temp_schema() as schema:
            if setup_sql:
                setup_result = sandbox.run_as_runner(setup_sql, schema=schema)
                if setup_result.status != "success":
                    return self.record_replay(
                        candidate_id,
                        "failed",
                        {
                            "phase": "setup",
                            "setup_sql": setup_sql,
                            "schema": schema,
                            "error": setup_result.error_message,
                        },
                        sandbox_schema=schema,
                        sandbox_env={"sandbox_type": "sql-temp-schema"},
                        error_message=setup_result.error_message,
                    )

            replay_result = sandbox.run_as_runner(candidate["proposed_content"], schema=schema)
            rows = [list(row) if isinstance(row, tuple) else row for row in replay_result.rows]
            validation_results = {
                "phase": "replay",
                "schema": schema,
                "row_count": len(rows),
                "rows": rows,
            }

            if replay_result.status != "success":
                return self.record_replay(
                    candidate_id,
                    "failed",
                    {**validation_results, "error": replay_result.error_message},
                    sandbox_schema=schema,
                    sandbox_env={"sandbox_type": "sql-temp-schema"},
                    error_message=replay_result.error_message,
                )

            assertion_error = _check_sql_assertions(assertions, rows)
            if assertion_error:
                return self.record_replay(
                    candidate_id,
                    "failed",
                    {**validation_results, "assertion_error": assertion_error},
                    sandbox_schema=schema,
                    sandbox_env={"sandbox_type": "sql-temp-schema"},
                    error_message=assertion_error,
                )

            return self.record_replay(
                candidate_id,
                "success",
                validation_results,
                sandbox_schema=schema,
                sandbox_env={"sandbox_type": "sql-temp-schema"},
            )

    def replay_code_candidate(self, candidate_id: str, function_name: str, args: list[Any] | None = None) -> str:
        from .sandbox import PythonSandbox

        candidate = self.store.fetch_one("SELECT * FROM improvement_candidates WHERE id = ?", [candidate_id])
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if candidate["patch_type"] != "code_patch":
            raise ValueError("replay_code_candidate only supports code_patch candidates")

        result = PythonSandbox().run_function(candidate["proposed_content"], function_name=function_name, args=args or [])
        validation_results = {
            "function_name": function_name,
            "args": args or [],
            "result": result.result,
            "sandbox": result.sandbox_env,
        }
        assertions = json.loads(candidate["validation_assertions"])
        if result.status == "success" and "expected_result" in assertions and result.result != assertions["expected_result"]:
            result_status = "failed"
            error_message = f"validation assertion failed: expected {assertions['expected_result']!r}, got {result.result!r}"
        else:
            result_status = result.status
            error_message = result.error_message
        return self.record_replay(
            candidate_id,
            result_status,
            validation_results,
            sandbox_env=result.sandbox_env,
            error_message=error_message,
        )

    def approve_candidate(self, candidate_id: str, approved_by: str, comments: str = "") -> str:
        approval_id = self.generate_id()
        self.store.execute(
            """
            INSERT INTO approvals (id, candidate_id, approved_by, decision, comments, created_at)
            VALUES (?, ?, ?, 'approved', ?, ?)
            """,
            [approval_id, candidate_id, approved_by, comments, _now()],
        )
        self._record_event("approval_granted", {"candidate_id": candidate_id, "approved_by": approved_by})
        return approval_id

    def reject_candidate(self, candidate_id: str, rejected_by: str, comments: str = "") -> str:
        candidate = self.store.fetch_one("SELECT * FROM improvement_candidates WHERE id = ?", [candidate_id])
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        approval_id = self.generate_id()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, candidate_id, approved_by, decision, comments, created_at)
                VALUES (?, ?, ?, 'rejected', ?, ?)
                """,
                [approval_id, candidate_id, rejected_by, comments, _now()],
            )
            conn.execute("UPDATE improvement_candidates SET status = 'rejected' WHERE id = ?", [candidate_id])
            conn.execute("UPDATE failures SET status = 'open' WHERE id = ?", [candidate["failure_id"]])
        self._record_event("approval_rejected", {"candidate_id": candidate_id, "rejected_by": rejected_by})
        return approval_id

    def apply_candidate(self, candidate_id: str) -> str:
        candidate = self.store.fetch_one("SELECT * FROM improvement_candidates WHERE id = ?", [candidate_id])
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if candidate["status"] != "sandbox_verified":
            raise Exception("candidate must be sandbox_verified before apply")
        approved = self.store.fetch_one(
            """
            SELECT * FROM approvals
            WHERE candidate_id = ? AND decision = 'approved'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [candidate_id],
        )
        if not approved:
            raise Exception("latest approval must be approved before apply")
        replay_success = self.store.fetch_one(
            "SELECT * FROM replays WHERE candidate_id = ? AND status = 'success' ORDER BY created_at DESC LIMIT 1",
            [candidate_id],
        )
        if not replay_success:
            raise Exception("successful replay required before apply")

        # ISSUE-002 緩解 + spec event-flow-v0.md §4：race condition 檢查必須在同一筆
        # transaction 內、且對 active artifact 列拿 row-level lock（FOR UPDATE）。
        # 否則兩個並發 apply 可能同時通過外部 hash 比對、再各自寫入。
        new_artifact_id = self.generate_id()
        race_detected = False
        try:
            with self.store.transaction() as conn:
                locked = conn.execute(
                    "SELECT id, version, content_hash FROM artifacts "
                    "WHERE name = ? AND is_active = TRUE FOR UPDATE",
                    [candidate["target_artifact_name"]],
                ).fetchone()
                if not locked:
                    race_detected = True
                    raise _RaceCondition()
                locked = _normalize_row(locked)
                if locked["content_hash"] != candidate["base_artifact_hash"]:
                    race_detected = True
                    raise _RaceCondition()

                conn.execute(
                    "UPDATE artifacts SET is_active = FALSE WHERE id = ?",
                    [locked["id"]],
                )
                conn.execute(
                    """
                    INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, TRUE, ?)
                    """,
                    [
                        new_artifact_id,
                        candidate["target_artifact_name"],
                        candidate["target_artifact_type"],
                        candidate["proposed_content"],
                        _hash(candidate["proposed_content"]),
                        locked["version"] + 1,
                        _now(),
                    ],
                )
                conn.execute("UPDATE improvement_candidates SET status = 'applied' WHERE id = ?", [candidate_id])
                conn.execute("UPDATE failures SET status = 'resolved' WHERE id = ?", [candidate["failure_id"]])
        except _RaceCondition:
            self.store.execute(
                "UPDATE improvement_candidates SET status = 'draft' WHERE id = ?",
                [candidate_id],
            )
            raise Exception("Race condition detected: Artifact has changed since verification")
        self._record_event("candidate_applied", {"candidate_id": candidate_id, "artifact_id": new_artifact_id})
        return new_artifact_id

    def force_replace_active_artifact_for_test(self, name: str, artifact_type: str, content: str) -> str:
        active = self.store.fetch_one("SELECT * FROM artifacts WHERE name = ? AND is_active = TRUE", [name])
        next_version = (active["version"] if active else 0) + 1
        artifact_id = self.generate_id()
        with self.store.transaction() as conn:
            conn.execute("UPDATE artifacts SET is_active = FALSE WHERE name = ? AND is_active = TRUE", [name])
            conn.execute(
                """
                INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, TRUE, ?)
                """,
                [artifact_id, name, artifact_type, content, _hash(content), next_version, _now()],
            )
        return artifact_id

    def find_orphan_attempts(self, older_than_seconds: int = 300) -> list[str]:
        rows = self.store.fetch_all(
            """
            SELECT le.attempt_id, MAX(le.created_at) AS last_active_at
            FROM attempt_lifecycle_events le
            LEFT JOIN attempts a ON le.attempt_id = a.id
            WHERE a.id IS NULL
            GROUP BY le.attempt_id
            """,
        )
        now = datetime.now(timezone.utc)
        orphan_ids = []
        for row in rows:
            last_active_at = datetime.fromisoformat(row["last_active_at"])
            if (now - last_active_at).total_seconds() >= older_than_seconds:
                orphan_ids.append(row["attempt_id"])
        return orphan_ids

    def reconcile_orphan_attempts(self, older_than_seconds: int = 300) -> list[str]:
        reconciled = []
        for attempt_id in self.find_orphan_attempts(older_than_seconds):
            self.finish_attempt(
                attempt_id,
                "failed",
                {"reconciled": True},
                error_message="System aborted: Orphan attempt detected and auto-reconciled",
            )
            reconciled.append(attempt_id)
        return reconciled

    def validate_sql_patch(self, sql: str) -> None:
        normalized = re.sub(r"\s+", " ", sql.strip().lower())
        for pattern, reason in _SQL_LINT_FORBIDDEN_PATTERNS:
            if re.search(pattern, normalized):
                raise SecurityError(f"SQL Lint Blocked: {reason}")

    def validate_python_patch(self, source: str) -> None:
        from .sandbox import validate_python_source

        validate_python_source(source)

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [self.generate_id(), event_type, _json(payload), _now()],
        )


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _json(value: Any):
    return json_param(value)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _failure_type(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    return error_message.split(":", 1)[0].strip() or "unknown"


def _check_sql_assertions(assertions: dict[str, Any], rows: list[Any]) -> str | None:
    """
    驗證 SQL replay 結果是否符合 candidate.validation_assertions。
    回傳 error message（不通過時）或 None（通過時）。
    支援的 assertion key：
      - expected_row_count: int
      - expected_result: list[list[Any]]  完全匹配 rows
    其餘 key 暫略過（forward-compat）。
    """
    if "expected_row_count" in assertions:
        expected = assertions["expected_row_count"]
        if len(rows) != expected:
            return f"validation assertion failed: expected_row_count={expected}, got {len(rows)}"
    if "expected_result" in assertions:
        expected = assertions["expected_result"]
        # 把 expected 內 tuple 化以便寬鬆比對（DB 回的是 tuple，rows 已 list 化）
        normalized_expected = [list(row) for row in expected]
        if rows != normalized_expected:
            return f"validation assertion failed: expected_result={normalized_expected!r}, got {rows!r}"
    return None


# SQL static lint 黑名單。每一條對應一個明確的 escape 風險。
# 候選 SQL 是要在 sandbox_temp_xxxx schema、由 sandbox_runner 角色執行的；
# 凡是能切回高權限、跨 schema 寫 production、或讀寫宿主檔案系統的語句都要在這裡擋下來。
_SQL_LINT_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bpublic\.", "public schema references are not allowed in candidate SQL"),
    (r"\btruncate\b", "TRUNCATE is not allowed in sandbox"),
    (r"\bdrop\s+table\b", "DROP TABLE is not allowed in sandbox"),
    (r"\bdrop\s+(?:schema|database)\b", "DROP SCHEMA/DATABASE is not allowed in sandbox"),
    (r"\balter\s+system\b", "ALTER SYSTEM is not allowed in sandbox"),
    (r"\breset\s+role\b", "RESET ROLE could escape sandbox role"),
    (r"\bset\s+role\b", "SET ROLE could escape sandbox role"),
    (r"\b(?:reset|set)\s+session\s+authorization\b", "SESSION AUTHORIZATION could escape sandbox role"),
    (r"\bsecurity\s+definer\b", "SECURITY DEFINER functions could elevate privileges"),
    (r"\b(?:create|alter|drop)\s+(?:role|user|group)\b", "ROLE/USER/GROUP management is not allowed in sandbox"),
    (r"\bgrant\s+", "GRANT is not allowed in sandbox"),
    (r"\brevoke\s+", "REVOKE is not allowed in sandbox"),
    (r"(?:\A|;\s*)copy\b", "COPY statement could read/write host files"),
    (r"\bpg_read_file\b|\bpg_read_binary_file\b|\bpg_ls_dir\b|\blo_import\b|\blo_export\b", "filesystem/largeobject functions are forbidden"),
]
