"""
EventReporter 測試。

用 in-memory SQLite 模擬 OHYA kanban.db 的最小 schema + sample 資料，
驗證同步到真實 PostgreSQL kernel 的對映、冪等性、容錯。
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from closed_loop_kernel import EventReporter, KanbanUnavailable
from tests.postgres_test_utils import build_postgres_store


def _build_kanban_fixture(path: Path, tenant: str = "ohya-test") -> None:
    """建一個最小的 kanban.db 模擬 OHYA 結構。"""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            assignee TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            tenant TEXT
        );
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            profile TEXT,
            status TEXT NOT NULL,
            outcome TEXT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            error TEXT,
            summary TEXT,
            metadata TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            run_id INTEGER,
            kind TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL
        );
        """
    )
    now = int(time.time())
    cur.executemany(
        "INSERT INTO tasks (id, title, assignee, status, created_at, tenant) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("task-1", "Publish article A", "cms-draft-executor", "done", now - 600, tenant),
            ("task-2", "Generate video B", "media-asset-generator", "running", now - 300, tenant),
            ("task-3", "Audit page C", "article-editor", "done", now - 200, tenant),
            ("task-4", "Sync GSC D", "gsc-pull-agent", "done", now - 100, None),  # NULL tenant → default
        ],
    )
    cur.executemany(
        "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("task-1", None, "created", json.dumps({"reason": "scheduled"}), now - 600),
            ("task-1", 1, "claimed", json.dumps({"worker_pid": 12345}), now - 500),
            ("task-2", None, "created", json.dumps({}), now - 300),
            ("task-3", None, "specified", json.dumps({"spec": "audit"}), now - 250),
            ("task-3", 2, "claimed", json.dumps({}), now - 240),
        ],
    )
    cur.executemany(
        "INSERT INTO task_runs (task_id, profile, status, outcome, started_at, ended_at, error, summary, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # run 1：成功（task-1, tenant=ohya-test）
            ("task-1", "cms-draft-executor", "done", "completed", now - 500, now - 480, None, "Article published", json.dumps({"post_id": 4751})),
            # run 2：失敗 crash（task-3, tenant=ohya-test）
            ("task-3", "article-editor", "crashed", "crashed", now - 240, now - 220, "ConnectionError: Zeabur API timeout", None, None),
            # run 3：失敗 timeout（task-4, NULL tenant → 用 default）
            ("task-4", "gsc-pull-agent", "timed_out", "timed_out", now - 90, now - 50, "GSC API request exceeded 60s", None, None),
        ],
    )
    conn.commit()
    conn.close()


@unittest.skipUnless(
    os.environ.get("KERNEL_DATABASE_URL") and os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET") == "1",
    "EventReporter integration test requires KERNEL_DATABASE_URL and destructive reset",
)
class EventReporterTests(unittest.TestCase):
    def setUp(self):
        self.store = build_postgres_store()
        self.addCleanup(self.store.close)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.kanban_path = Path(self.tmpdir.name) / "kanban.db"
        _build_kanban_fixture(self.kanban_path)
        self.reporter = EventReporter(
            kanban_db_path=str(self.kanban_path),
            kernel_url=os.environ["KERNEL_DATABASE_URL"],
            tenant_default="ohya",
        )

    def test_first_sync_imports_events_attempts_and_failures(self):
        result = self.reporter.sync()

        # 5 個 task_events 全部進來
        self.assertEqual(result.events_imported, 5)
        # 3 個 task_run 都已 ended → 都進來；其中 2 個是失敗
        self.assertEqual(result.attempts_imported, 3)
        self.assertEqual(result.failures_opened, 2)
        # checkpoint 已更新
        self.assertEqual(result.last_event_id, 5)
        self.assertEqual(result.last_run_id, 3)

        # 驗證資料庫狀態
        event_count = self.store.scalar(
            "SELECT COUNT(*) FROM events WHERE event_type LIKE ?",
            ["ohya_kanban_%"],
        )
        self.assertEqual(event_count, 5)

        attempt_count = self.store.scalar("SELECT COUNT(*) FROM attempts")
        self.assertEqual(attempt_count, 3)

        # 找 crash 失敗（task-3, tenant=ohya-test）
        crash_failure = self.store.fetch_one(
            "SELECT * FROM failures WHERE failure_type = ?",
            ["crash"],
        )
        self.assertIsNotNone(crash_failure)
        ctx = json.loads(crash_failure["context"]) if isinstance(crash_failure["context"], str) else crash_failure["context"]
        self.assertEqual(ctx["tenant"], "ohya-test")
        self.assertEqual(ctx["kanban_task_id"], "task-3")
        self.assertIn("ConnectionError", ctx["error"])

        # 找 timeout 失敗（task-4, NULL tenant → default 'ohya'）
        timeout_failure = self.store.fetch_one(
            "SELECT * FROM failures WHERE failure_type = ?",
            ["timeout"],
        )
        self.assertIsNotNone(timeout_failure)
        ctx2 = json.loads(timeout_failure["context"]) if isinstance(timeout_failure["context"], str) else timeout_failure["context"]
        self.assertEqual(ctx2["tenant"], "ohya")
        self.assertEqual(ctx2["kanban_task_id"], "task-4")

    def test_second_sync_is_idempotent(self):
        # 跑兩次 sync，第二次不該重複塞任何東西
        first = self.reporter.sync()
        second = self.reporter.sync()

        self.assertEqual(second.events_imported, 0)
        self.assertEqual(second.attempts_imported, 0)
        self.assertEqual(second.failures_opened, 0)
        # checkpoint 不會倒退
        self.assertEqual(second.last_event_id, first.last_event_id)
        self.assertEqual(second.last_run_id, first.last_run_id)

        # 確認資料庫沒有重複（3 個 task_run 都 ended）
        attempt_count = self.store.scalar("SELECT COUNT(*) FROM attempts")
        self.assertEqual(attempt_count, 3)

    def test_incremental_sync_picks_up_new_events_only(self):
        self.reporter.sync()

        # 在 kanban.db 加新事件 + 新 run
        conn = sqlite3.connect(str(self.kanban_path))
        cur = conn.cursor()
        now = int(time.time())
        cur.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            ("task-2", None, "decomposed", "{}", now),
        )
        cur.execute(
            "INSERT INTO task_runs (task_id, profile, status, outcome, started_at, ended_at, error, summary, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("task-2", "media-asset-generator", "done", "timed_out", now - 100, now - 50, "Quota exceeded", None, None),
        )
        conn.commit()
        conn.close()

        result = self.reporter.sync()

        self.assertEqual(result.events_imported, 1)
        self.assertEqual(result.attempts_imported, 1)
        self.assertEqual(result.failures_opened, 1)
        # 應該有 3 個 failure：原有 crash + timeout + 新增 timeout（task-2 也 timed_out）
        failures = self.store.fetch_all("SELECT failure_type FROM failures ORDER BY created_at")
        self.assertEqual(sorted([f["failure_type"] for f in failures]), ["crash", "timeout", "timeout"])

    def test_tenant_default_applied_when_task_tenant_null(self):
        self.reporter.sync()

        # task-4 的 tenant 是 NULL，對應的 failure（timeout）應該用 default "ohya"
        failure = self.store.fetch_one(
            "SELECT context FROM failures WHERE failure_type = ?",
            ["timeout"],
        )
        ctx = json.loads(failure["context"]) if isinstance(failure["context"], str) else failure["context"]
        self.assertEqual(ctx["tenant"], "ohya")
        self.assertEqual(ctx["kanban_task_id"], "task-4")

    def test_profile_filter_imports_only_cms_draft_executor_slice(self):
        reporter = EventReporter(
            kanban_db_path=str(self.kanban_path),
            kernel_url=os.environ["KERNEL_DATABASE_URL"],
            tenant_default="ohya",
            profile_filter="cms-draft-executor",
        )

        result = reporter.sync()

        self.assertEqual(result.source_profile, "cms-draft-executor")
        self.assertEqual(result.events_imported, 2)
        self.assertEqual(result.attempts_imported, 1)
        self.assertEqual(result.failures_opened, 0)
        self.assertEqual(result.last_event_id, 5)
        self.assertEqual(result.last_run_id, 3)
        self.assertGreaterEqual(result.skipped_by_reason["profile_mismatch"], 1)

        attempts = self.store.fetch_all("SELECT input FROM attempts")
        self.assertEqual(len(attempts), 1)
        payload = json.loads(attempts[0]["input"]) if isinstance(attempts[0]["input"], str) else attempts[0]["input"]
        self.assertEqual(payload["profile"], "cms-draft-executor")
        self.assertEqual(payload["kanban_task_id"], "task-1")

        event_payloads = self.store.fetch_all(
            "SELECT payload FROM events WHERE event_type LIKE ? ORDER BY created_at",
            ["ohya_kanban_%"],
        )
        for event in event_payloads:
            payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
            self.assertEqual(payload["source_profile"], "cms-draft-executor")

    def test_profile_slice_skips_bad_json_without_importing_dirty_attempt(self):
        conn = sqlite3.connect(str(self.kanban_path))
        cur = conn.cursor()
        now = int(time.time())
        cur.execute(
            "INSERT INTO tasks (id, title, assignee, status, created_at, tenant) VALUES (?, ?, ?, ?, ?, ?)",
            ("task-bad-json", "Bad JSON task", "cms-draft-executor", "done", now - 20, "ohya-test"),
        )
        cur.execute(
            "INSERT INTO task_runs (task_id, profile, status, outcome, started_at, ended_at, error, summary, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("task-bad-json", "cms-draft-executor", "done", "completed", now - 19, now - 18, None, "dirty", "{bad-json"),
        )
        run_id = cur.lastrowid
        cur.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            ("task-bad-json", run_id, "claimed", "{bad-json", now - 19),
        )
        conn.commit()
        conn.close()

        reporter = EventReporter(
            kanban_db_path=str(self.kanban_path),
            kernel_url=os.environ["KERNEL_DATABASE_URL"],
            tenant_default="ohya",
            profile_filter="cms-draft-executor",
        )

        result = reporter.sync()

        self.assertEqual(result.skipped_by_reason["bad_json"], 2)
        attempt_count = self.store.scalar("SELECT COUNT(*) FROM attempts")
        self.assertEqual(attempt_count, 1)

    def test_profile_slice_skips_incomplete_and_unsupported_runs(self):
        conn = sqlite3.connect(str(self.kanban_path))
        cur = conn.cursor()
        now = int(time.time())
        cur.executemany(
            "INSERT INTO tasks (id, title, assignee, status, created_at, tenant) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("task-running", "Still running", "cms-draft-executor", "running", now - 30, "ohya-test"),
                ("task-released", "Released task", "cms-draft-executor", "released", now - 20, "ohya-test"),
            ],
        )
        cur.executemany(
            "INSERT INTO task_runs (task_id, profile, status, outcome, started_at, ended_at, error, summary, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("task-running", "cms-draft-executor", "running", None, now - 29, None, None, None, None),
                ("task-released", "cms-draft-executor", "released", "released", now - 19, now - 18, None, None, None),
            ],
        )
        conn.commit()
        conn.close()

        reporter = EventReporter(
            kanban_db_path=str(self.kanban_path),
            kernel_url=os.environ["KERNEL_DATABASE_URL"],
            tenant_default="ohya",
            profile_filter="cms-draft-executor",
        )

        result = reporter.sync()

        self.assertEqual(result.skipped_by_reason["missing_required_field"], 1)
        self.assertEqual(result.skipped_by_reason["unsupported_outcome"], 1)
        attempt_count = self.store.scalar("SELECT COUNT(*) FROM attempts")
        self.assertEqual(attempt_count, 1)

    def test_missing_kanban_db_raises_unavailable(self):
        bad_reporter = EventReporter(
            kanban_db_path="/nonexistent/path/kanban.db",
            kernel_url=os.environ["KERNEL_DATABASE_URL"],
        )
        with self.assertRaises(KanbanUnavailable):
            bad_reporter.sync()


if __name__ == "__main__":
    unittest.main()
