from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .store import KernelStore


class SecurityError(Exception):
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
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
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

        active = self.store.fetch_one(
            "SELECT * FROM artifacts WHERE name = ? AND is_active = 1",
            [candidate["target_artifact_name"]],
        )
        if not active or active["content_hash"] != candidate["base_artifact_hash"]:
            self.store.execute("UPDATE improvement_candidates SET status = 'draft' WHERE id = ?", [candidate_id])
            raise Exception("Race condition detected: Artifact has changed since verification")

        new_artifact_id = self.generate_id()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE artifacts SET is_active = 0 WHERE name = ? AND is_active = 1",
                [candidate["target_artifact_name"]],
            )
            conn.execute(
                """
                INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                [
                    new_artifact_id,
                    candidate["target_artifact_name"],
                    candidate["target_artifact_type"],
                    candidate["proposed_content"],
                    _hash(candidate["proposed_content"]),
                    active["version"] + 1,
                    _now(),
                ],
            )
            conn.execute("UPDATE improvement_candidates SET status = 'applied' WHERE id = ?", [candidate_id])
            conn.execute("UPDATE failures SET status = 'resolved' WHERE id = ?", [candidate["failure_id"]])
        self._record_event("candidate_applied", {"candidate_id": candidate_id, "artifact_id": new_artifact_id})
        return new_artifact_id

    def force_replace_active_artifact_for_test(self, name: str, artifact_type: str, content: str) -> str:
        active = self.store.fetch_one("SELECT * FROM artifacts WHERE name = ? AND is_active = 1", [name])
        next_version = (active["version"] if active else 0) + 1
        artifact_id = self.generate_id()
        with self.store.transaction() as conn:
            conn.execute("UPDATE artifacts SET is_active = 0 WHERE name = ? AND is_active = 1", [name])
            conn.execute(
                """
                INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
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
        if "public." in normalized or "truncate" in normalized or re.search(r"\bdrop\s+table\b", normalized):
            raise SecurityError("SQL Lint Blocked: Forbidden keyword or public schema reference")

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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _failure_type(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    return error_message.split(":", 1)[0].strip() or "unknown"
