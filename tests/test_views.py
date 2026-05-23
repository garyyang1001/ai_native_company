import unittest

from closed_loop_kernel import KernelEngine
from closed_loop_kernel.views import render_approvals_view, render_event_detail_view, render_events_view, render_improvements_view
from tests.postgres_test_utils import build_postgres_store


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.store = build_postgres_store()
        self.addCleanup(self.store.close)
        self.engine = KernelEngine(self.store)

    def test_events_view_lists_lifecycle_and_failure_without_overwriting_history(self):
        attempt_id = self.engine.start_attempt({"query": "broken"})
        self.engine.finish_attempt(attempt_id, "failed", {"query": "broken"}, error_message="TypeError: broken")

        html = render_events_view(self.store)
        detail = render_event_detail_view(self.store, attempt_id)

        self.assertNotIn("attempt_lifecycle_events", html)
        self.assertIn("任務開始", html)
        self.assertIn("執行中", html)
        self.assertIn("任務完成", html)
        self.assertIn("執行", html)
        self.assertIn("執行失敗", detail)
        self.assertIn("錯誤原因", detail)
        self.assertIn("任務開始", detail)
        self.assertNotIn("Attempt ", detail)
        self.assertNotIn("Status:", detail)
        self.assertNotIn("Tool Calls", detail)
        self.assertNotIn(attempt_id, detail)
        self.assertIn("TypeError: broken", detail)

    def test_improvements_and_approvals_views_show_candidate_gate_state(self):
        artifact_id = self.engine.create_artifact("skills.normalize", "python", "def normalize(v): return v")
        failure_id = self.engine.create_failure_for_test("TypeError")
        candidate_id = self.engine.propose_improvement(
            failure_id,
            artifact_id,
            "code_patch",
            "def normalize(v): return v or 0",
            {"unit": "ok"},
            {"restore": "previous"},
        )

        self.assertIn("草稿", render_improvements_view(self.store))
        approvals = render_approvals_view(self.store)
        self.assertIn("disabled", approvals)
        self.assertIn("先完成 replay", approvals)

        self.engine.record_replay(candidate_id, "success", {"unit": "passed"})
        approvals = render_approvals_view(self.store)
        self.assertIn("批准並套用", approvals)
        self.assertNotIn("先完成 replay", approvals)

    def test_approvals_view_has_human_empty_state(self):
        self.assertIn("目前沒有待審核修正案", render_approvals_view(self.store))


if __name__ == "__main__":
    unittest.main()
