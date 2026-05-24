import os
import threading
import unittest

from closed_loop_kernel import KernelEngine, SecurityError, SqlSandbox
from tests.postgres_test_utils import build_postgres_store


def _skip_unless_postgres_available():
    if not os.environ.get("KERNEL_DATABASE_URL"):
        raise unittest.SkipTest("KERNEL_DATABASE_URL is required for SqlSandbox tests")


class SqlSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _skip_unless_postgres_available()
        cls.admin_url = os.environ["KERNEL_DATABASE_URL"]
        cls.sandbox = SqlSandbox(cls.admin_url, runner_role="sandbox_runner_test")
        cls.sandbox.ensure_role()

    def test_ensure_role_is_idempotent(self):
        # 再呼叫一次不該爆，且 role 仍然存在。
        self.sandbox.ensure_role()
        import psycopg
        with psycopg.connect(self.admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (self.sandbox.runner_role,))
                self.assertIsNotNone(cur.fetchone())

    def test_temp_schema_is_created_and_dropped(self):
        import psycopg
        with self.sandbox.temp_schema() as schema:
            self.assertTrue(schema.startswith("sandbox_temp_"))
            with psycopg.connect(self.admin_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,))
                    self.assertIsNotNone(cur.fetchone(), f"{schema} should exist inside the with block")
        # 離開後該 schema 必須消失
        with psycopg.connect(self.admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,))
                self.assertIsNone(cur.fetchone(), f"{schema} should be dropped after exit")

    def test_temp_schema_is_cleaned_up_even_if_caller_raises(self):
        import psycopg
        captured_schema = None
        with self.assertRaises(RuntimeError):
            with self.sandbox.temp_schema() as schema:
                captured_schema = schema
                raise RuntimeError("simulated failure inside replay")
        with psycopg.connect(self.admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (captured_schema,))
                self.assertIsNone(cur.fetchone(), "schema should be dropped even on exception")

    def test_run_as_runner_creates_and_queries_in_temp_schema(self):
        with self.sandbox.temp_schema() as schema:
            create = self.sandbox.run_as_runner(
                "CREATE TABLE t (id int, name text); "
                "INSERT INTO t VALUES (1, 'alice'), (2, 'bob');",
                schema=schema,
            )
            self.assertEqual(create.status, "success", create.error_message)

            query = self.sandbox.run_as_runner("SELECT id, name FROM t ORDER BY id", schema=schema)
            self.assertEqual(query.status, "success", query.error_message)
            self.assertEqual(query.rows, [(1, "alice"), (2, "bob")])

    def test_run_as_runner_cannot_write_to_public_schema(self):
        # public schema 已對 sandbox_runner REVOKE 所有權限；嘗試 CREATE TABLE public.evil 應失敗
        with self.sandbox.temp_schema() as schema:
            result = self.sandbox.run_as_runner(
                "CREATE TABLE public.evil_table (id int)",
                schema=schema,
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("permission denied", (result.error_message or "").lower())

    def test_run_as_runner_cannot_select_from_kernel_state_tables(self):
        # 即使 sandbox 連線是 admin URL，SET LOCAL ROLE 之後對 public.attempts 也應該被拒
        with self.sandbox.temp_schema() as schema:
            result = self.sandbox.run_as_runner(
                "SELECT 1 FROM public.attempts LIMIT 1",
                schema=schema,
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("permission denied", (result.error_message or "").lower())

    def test_concurrent_temp_schemas_get_distinct_names_and_clean_up(self):
        # 並發開 N 個 temp_schema，個個獨立、互不污染、最後全清乾淨
        thread_count = 6
        schemas: list[str] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker():
            try:
                with self.sandbox.temp_schema() as schema:
                    create = self.sandbox.run_as_runner(
                        "CREATE TABLE local_t (n int); INSERT INTO local_t VALUES (42);",
                        schema=schema,
                    )
                    if create.status != "success":
                        raise AssertionError(f"create failed: {create.error_message}")
                    query = self.sandbox.run_as_runner("SELECT n FROM local_t", schema=schema)
                    if query.rows != [(42,)]:
                        raise AssertionError(f"unexpected rows: {query.rows!r}")
                    with lock:
                        schemas.append(schema)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"worker errors: {errors!r}")
        self.assertEqual(len(schemas), thread_count)
        self.assertEqual(len(set(schemas)), thread_count, "schemas must all be distinct")

        # 所有 schema 必須已被清除
        import psycopg
        with psycopg.connect(self.admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)",
                    (schemas,),
                )
                leftover = [row[0] for row in cur.fetchall()]
        self.assertEqual(leftover, [], f"these schemas leaked: {leftover!r}")


class ReplaySqlCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _skip_unless_postgres_available()
        cls.admin_url = os.environ["KERNEL_DATABASE_URL"]
        cls.sandbox = SqlSandbox(cls.admin_url, runner_role="sandbox_runner_test")
        cls.sandbox.ensure_role()

    def setUp(self):
        # 每個 test 都跑 reset_for_test 確保 kernel 資料表乾淨；
        # 注意：reset 會 DROP SCHEMA public，所以 sandbox_runner 之前對 public 的 REVOKE 也跟著沒了，
        # 必須重跑 ensure_role 把權限狀態裝回來。
        self.store = build_postgres_store()
        self.addCleanup(self.store.close)
        self.engine = KernelEngine(self.store)
        self.sandbox.ensure_role()

    def _seed_candidate(self, proposed_sql: str, validation_assertions: dict) -> str:
        artifact_id = self.engine.create_artifact(
            "text_to_sql.prompts.documents",
            "sql",
            "-- placeholder original SQL",
        )
        failure_id = self.engine.create_failure_for_test("relation_does_not_exist")
        return self.engine.propose_improvement(
            failure_id,
            artifact_id,
            "sql_patch",
            proposed_sql,
            validation_assertions,
            {"restore_artifact_id": artifact_id},
        )

    def test_replay_sql_candidate_marks_sandbox_verified_on_success(self):
        candidate_id = self._seed_candidate(
            "SELECT id, name FROM local_docs ORDER BY id",
            validation_assertions={"expected_row_count": 2, "expected_result": [[1, "alice"], [2, "bob"]]},
        )

        replay_id = self.engine.replay_sql_candidate(
            candidate_id,
            self.sandbox,
            setup_sql="CREATE TABLE local_docs (id int, name text); INSERT INTO local_docs VALUES (1, 'alice'), (2, 'bob');",
        )

        replay = self.store.fetch_one("SELECT * FROM replays WHERE id = ?", [replay_id])
        self.assertEqual(replay["status"], "success", replay.get("error_message"))
        self.assertTrue(replay["sandbox_schema"].startswith("sandbox_temp_"))
        self.assertEqual(
            self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]),
            "sandbox_verified",
        )

    def test_replay_sql_candidate_records_failure_when_assertion_violated(self):
        candidate_id = self._seed_candidate(
            "SELECT id FROM local_docs",
            validation_assertions={"expected_row_count": 5},  # 但 setup 只塞 2 列
        )

        replay_id = self.engine.replay_sql_candidate(
            candidate_id,
            self.sandbox,
            setup_sql="CREATE TABLE local_docs (id int); INSERT INTO local_docs VALUES (1), (2);",
        )

        replay = self.store.fetch_one("SELECT * FROM replays WHERE id = ?", [replay_id])
        self.assertEqual(replay["status"], "failed")
        self.assertIn("expected_row_count=5", replay["error_message"])
        self.assertEqual(
            self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]),
            "draft",
        )

    def test_replay_sql_candidate_records_failure_when_replay_sql_errors(self):
        candidate_id = self._seed_candidate(
            "SELECT * FROM nonexistent_table",
            validation_assertions={},
        )

        replay_id = self.engine.replay_sql_candidate(candidate_id, self.sandbox)

        replay = self.store.fetch_one("SELECT * FROM replays WHERE id = ?", [replay_id])
        self.assertEqual(replay["status"], "failed")
        self.assertIn("does not exist", (replay["error_message"] or "").lower())
        self.assertEqual(
            self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]),
            "draft",
        )

    def test_replay_sql_candidate_rejects_lint_violating_proposed_content(self):
        candidate_id = self._seed_candidate(
            "DROP TABLE public.attempts",
            validation_assertions={},
        )

        with self.assertRaisesRegex(SecurityError, "SQL Lint Blocked"):
            self.engine.replay_sql_candidate(candidate_id, self.sandbox)

    def test_replay_sql_candidate_rejects_wrong_patch_type(self):
        # 故意建立一個 code_patch candidate，再呼叫 sql replay 應該拒絕
        artifact_id = self.engine.create_artifact("skill.foo", "python", "def foo():\n    return 1\n")
        failure_id = self.engine.create_failure_for_test("AssertionError")
        candidate_id = self.engine.propose_improvement(
            failure_id,
            artifact_id,
            "code_patch",
            "def foo():\n    return 2\n",
            {},
            {"restore_artifact_id": artifact_id},
        )

        with self.assertRaisesRegex(ValueError, "only supports sql_patch"):
            self.engine.replay_sql_candidate(candidate_id, self.sandbox)


if __name__ == "__main__":
    unittest.main()
