import os
import threading
import unittest

from closed_loop_kernel import SqlSandbox


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


if __name__ == "__main__":
    unittest.main()
