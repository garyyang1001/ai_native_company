import json
import unittest

from closed_loop_kernel.engine import KernelEngine
from closed_loop_kernel.failure_analyzer import FailureAnalyzer
from tests.postgres_test_utils import build_postgres_store


class FailureAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.store = build_postgres_store()
        self.addCleanup(self.store.close)
        self.engine = KernelEngine(self.store)

    def test_crash_failure_creates_sandbox_verified_candidate(self):
        failure_id = self.engine.create_failure_for_test("crash")

        result = FailureAnalyzer(self.store).analyze_open_failures()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["sandbox_passed"], 1)
        candidate_id = result["candidates"][0]
        self.assertEqual(
            self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]),
            "sandbox_verified",
        )
        self.assertEqual(
            self.store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]),
            "proposed",
        )

    def test_timeout_failure_is_left_open_in_auto_sandbox_mode(self):
        failure_id = self.engine.create_failure_for_test("timeout")

        result = FailureAnalyzer(self.store).analyze_open_failures()

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(
            self.store.scalar("SELECT COUNT(*) FROM improvement_candidates WHERE failure_id = ?", [failure_id]),
            0,
        )
        self.assertEqual(
            self.store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]),
            "open",
        )
        event = self.store.fetch_one("SELECT payload FROM events WHERE event_type = ?", ["ohya_analyzer_skip"])
        payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
        self.assertEqual(payload["reason"], "unsupported_failure_type_for_auto_sandbox")


if __name__ == "__main__":
    unittest.main()
