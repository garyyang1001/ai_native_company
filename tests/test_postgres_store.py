import unittest
import uuid
from datetime import datetime, timezone

from closed_loop_kernel.postgres import render_postgres_schema
from closed_loop_kernel.store import RESET_CONFIRMATION, JsonParam, KernelStore, json_param


class FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakePostgresConnection:
    def __init__(self):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.next_rows = []

    def execute(self, sql, params=None):
        self.executed.append((sql, tuple(params or ())))
        return FakeCursor(self.next_rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class KernelStorePostgresTests(unittest.TestCase):
    def test_initialize_executes_postgres_schema(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        store.initialize()

        self.assertEqual(conn.executed[0][0], render_postgres_schema())
        self.assertEqual(conn.commits, 1)

    def test_reset_for_test_requires_explicit_confirmation(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        with self.assertRaisesRegex(RuntimeError, "explicit destructive reset confirmation"):
            store.reset_for_test()

        store.reset_for_test(confirm=RESET_CONFIRMATION)

        self.assertEqual(conn.executed[-1][0], "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        self.assertEqual(conn.commits, 1)

    def test_queries_translate_engine_placeholders_to_psycopg_placeholders(self):
        conn = FakePostgresConnection()
        conn.next_rows = [{"id": "attempt_1", "status": "failed"}]
        store = KernelStore(conn)

        rows = store.fetch_all("SELECT * FROM attempts WHERE id = ? AND status = ?", ["attempt_1", "failed"])

        self.assertEqual(rows, [{"id": "attempt_1", "status": "failed"}])
        self.assertEqual(
            conn.executed[-1],
            ("SELECT * FROM attempts WHERE id = %s AND status = %s", ("attempt_1", "failed")),
        )

    def test_is_active_numeric_compat_queries_translate_to_postgres_booleans(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        store.fetch_all("SELECT * FROM artifacts WHERE is_active = 1")
        self.assertEqual(conn.executed[-1][0], "SELECT * FROM artifacts WHERE is_active = TRUE")

        store.fetch_all("SELECT * FROM artifacts WHERE is_active = 0")
        self.assertEqual(conn.executed[-1][0], "SELECT * FROM artifacts WHERE is_active = FALSE")

    def test_json_looking_text_params_are_not_wrapped_as_json(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        store.execute("INSERT INTO artifacts (content) VALUES (?)", ['{"prompt":"keep this as text"}'])

        self.assertEqual(conn.executed[-1][1], ('{"prompt":"keep this as text"}',))

    def test_explicit_json_params_are_wrapped_for_postgres_json_columns(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        store.execute("INSERT INTO events (payload) VALUES (?)", [json_param({"a": 1})])

        self.assertNotIsInstance(conn.executed[-1][1][0], JsonParam)

    def test_rows_normalize_postgres_native_values_to_previous_store_contract(self):
        conn = FakePostgresConnection()
        row_id = uuid.uuid4()
        created_at = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
        conn.next_rows = [{"id": row_id, "created_at": created_at, "payload": {"ok": True}, "items": [1]}]
        store = KernelStore(conn)

        row = store.fetch_one("SELECT * FROM events")

        self.assertEqual(row["id"], str(row_id))
        self.assertEqual(row["created_at"], created_at.isoformat())
        self.assertEqual(row["payload"], '{"ok": true}')
        self.assertEqual(row["items"], "[1]")

    def test_transactions_translate_queries_and_commit_or_rollback(self):
        conn = FakePostgresConnection()
        store = KernelStore(conn)

        with store.transaction() as tx:
            tx.execute("UPDATE failures SET status = ? WHERE id = ?", ["resolved", "failure_1"])

        self.assertEqual(
            conn.executed[-1],
            ("UPDATE failures SET status = %s WHERE id = %s", ("resolved", "failure_1")),
        )
        self.assertEqual(conn.commits, 1)

        with self.assertRaises(RuntimeError):
            with store.transaction() as tx:
                tx.execute("UPDATE failures SET status = ? WHERE id = ?", ["open", "failure_1"])
                raise RuntimeError("boom")

        self.assertEqual(conn.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
