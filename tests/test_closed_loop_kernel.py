import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from closed_loop_kernel import KernelEngine, KernelStore, SecurityError


class ClosedLoopKernelTests(unittest.TestCase):
    def setUp(self):
        self.store = KernelStore.in_memory()
        self.store.initialize()
        self.engine = KernelEngine(self.store)

    def test_failed_attempt_is_single_insert_and_append_only(self):
        attempt_id = self.engine.start_attempt({"query": "raise TypeError"})

        self.assertEqual(self.store.fetch_all("SELECT * FROM attempts WHERE id = ?", [attempt_id]), [])
        lifecycle_states = [
            row["state"]
            for row in self.store.fetch_all(
                "SELECT state FROM attempt_lifecycle_events WHERE attempt_id = ? ORDER BY created_at",
                [attempt_id],
            )
        ]
        self.assertEqual(lifecycle_states, ["started", "running"])

        self.engine.finish_attempt(
            attempt_id,
            status="failed",
            input_payload={"query": "raise TypeError"},
            error_message="TypeError: unsupported operand type",
            tool_calls=[
                {"tool_name": "query_database", "arguments": {"sql": "SELECT broken"}, "status": "failed"}
            ],
            decisions=[
                {"decision_maker": "policy_engine", "action_taken": "allowed", "reason": "read-only query"}
            ],
        )

        attempts = self.store.fetch_all("SELECT * FROM attempts WHERE id = ?", [attempt_id])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertIn("TypeError", attempts[0]["error_message"])
        self.assertEqual(
            self.store.scalar("SELECT COUNT(*) FROM failures WHERE attempt_id = ?", [attempt_id]),
            1,
        )

        with self.assertRaisesRegex(Exception, "attempts is append-only"):
            self.store.execute("UPDATE attempts SET status = 'success' WHERE id = ?", [attempt_id])

    def test_candidate_apply_requires_replay_approval_and_matching_artifact_hash(self):
        artifact_id = self.engine.create_artifact("skills.compute_score", "python", "def compute(): return 1")
        attempt_id = self.engine.start_attempt({"skill": "compute_score"})
        self.engine.finish_attempt(
            attempt_id,
            status="failed",
            input_payload={"skill": "compute_score"},
            error_message="TypeError: None cannot be added",
        )
        failure_id = self.store.scalar("SELECT id FROM failures WHERE attempt_id = ?", [attempt_id])

        candidate_id = self.engine.propose_improvement(
            failure_id,
            target_artifact_id=artifact_id,
            patch_type="code_patch",
            proposed_content="def compute(): return 2",
            validation_assertions={"unit": "compute_returns_number"},
            rollback_plan={"restore_artifact_id": artifact_id},
        )

        with self.assertRaisesRegex(Exception, "sandbox_verified"):
            self.engine.apply_candidate(candidate_id)

        self.engine.record_replay(candidate_id, status="success", validation_results={"unit": "passed"})
        self.engine.approve_candidate(candidate_id, approved_by="human_dri:gary", comments="sandbox passed")
        new_artifact_id = self.engine.apply_candidate(candidate_id)

        active = self.store.fetch_one(
            "SELECT * FROM artifacts WHERE name = ? AND is_active = 1",
            ["skills.compute_score"],
        )
        self.assertEqual(active["id"], new_artifact_id)
        self.assertEqual(active["content"], "def compute(): return 2")
        self.assertEqual(self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "applied")
        self.assertEqual(self.store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]), "resolved")

    def test_artifact_hash_mismatch_blocks_apply_and_keeps_candidate_draft(self):
        artifact_id = self.engine.create_artifact("prompts.search", "prompt", "v1")
        failure_id = self.engine.create_failure_for_test("logic_fault")
        candidate_id = self.engine.propose_improvement(
            failure_id,
            target_artifact_id=artifact_id,
            patch_type="prompt_update",
            proposed_content="v2",
            validation_assertions={"replay": "ok"},
            rollback_plan={"restore": "v1"},
        )
        self.engine.record_replay(candidate_id, status="success", validation_results={"replay": "ok"})
        self.engine.approve_candidate(candidate_id, approved_by="human_dri:gary", comments="ok")
        self.engine.force_replace_active_artifact_for_test("prompts.search", "prompt", "concurrent-v2")

        with self.assertRaisesRegex(Exception, "Artifact has changed"):
            self.engine.apply_candidate(candidate_id)

        self.assertEqual(self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "draft")
        self.assertEqual(
            self.store.scalar("SELECT content FROM artifacts WHERE name = ? AND is_active = 1", ["prompts.search"]),
            "concurrent-v2",
        )

    def test_orphan_lifecycle_is_reconciled_as_failed_attempt(self):
        attempt_id = self.engine.generate_id()
        old = datetime.now(timezone.utc) - timedelta(minutes=6)
        self.engine.record_lifecycle_event(attempt_id, "started", created_at=old)
        self.engine.record_lifecycle_event(attempt_id, "running", created_at=old + timedelta(seconds=30))

        self.assertEqual(len(self.engine.find_orphan_attempts(older_than_seconds=300)), 1)
        reconciled = self.engine.reconcile_orphan_attempts(older_than_seconds=300)

        self.assertEqual(reconciled, [attempt_id])
        attempt = self.store.fetch_one("SELECT * FROM attempts WHERE id = ?", [attempt_id])
        self.assertEqual(attempt["status"], "failed")
        self.assertIn("Orphan attempt detected", attempt["error_message"])
        self.assertEqual(
            self.store.scalar(
                "SELECT state FROM attempt_lifecycle_events WHERE attempt_id = ? ORDER BY created_at DESC LIMIT 1",
                [attempt_id],
            ),
            "finished",
        )


class SandboxLintTests(unittest.TestCase):
    def test_sql_and_python_lints_block_known_unsafe_patches(self):
        store = KernelStore.in_memory()
        store.initialize()
        engine = KernelEngine(store)

        with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked"):
            engine.validate_sql_patch("DROP TABLE public.attempts;")

        with self.assertRaisesRegex(SecurityError, "Python AST Lint Blocked"):
            engine.validate_python_patch("import os\nos.system('rm -rf /')")

    def test_sql_and_python_lints_allow_minimal_safe_patches(self):
        store = KernelStore.in_memory()
        store.initialize()
        engine = KernelEngine(store)

        engine.validate_sql_patch("CREATE INDEX idx_documents_title ON documents(title);")
        engine.validate_python_patch("def normalize(value):\n    return value or 0\n")


if __name__ == "__main__":
    unittest.main()
