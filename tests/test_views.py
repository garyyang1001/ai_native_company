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

    def test_views_render_sql_patch_with_sandbox_schema_and_replay_sample(self):
        # 建一個 sql_patch candidate 並手動寫一筆成功 replay（含 sandbox_schema + rows），
        # 驗證 UI 呈現「SQL 修正」標籤、沙盒 schema、replay 樣本。
        artifact_id = self.engine.create_artifact("text_to_sql.prompts.docs", "sql", "SELECT 1")
        failure_id = self.engine.create_failure_for_test("relation_does_not_exist")
        candidate_id = self.engine.propose_improvement(
            failure_id,
            artifact_id,
            "sql_patch",
            "SELECT d.title FROM documents d JOIN document_tags_mapping t ON d.id = t.document_id WHERE t.tag_name = 'Important'",
            {"expected_row_count": 1},
            {"restore_artifact_id": artifact_id},
        )
        self.engine.record_replay(
            candidate_id,
            "success",
            {"phase": "replay", "schema": "sandbox_temp_abcdef123456", "row_count": 1, "rows": [["Q2 Strategy"]]},
            sandbox_schema="sandbox_temp_abcdef123456",
            sandbox_env={"sandbox_type": "sql-temp-schema"},
        )

        improvements = render_improvements_view(self.store)
        approvals = render_approvals_view(self.store)

        # /improvements 表格：新增了「沙盒 schema」欄，sql_patch 顯示中文標籤
        self.assertIn("SQL 修正", improvements)
        self.assertIn("沙盒 schema", improvements)
        self.assertIn("sandbox_temp_abcdef123456", improvements)

        # /approvals 卡片：含 patch_type 標籤 + sandbox schema + replay 樣本
        self.assertIn("SQL 修正", approvals)
        self.assertIn("sandbox_temp_abcdef123456", approvals)
        self.assertIn("Replay 結果", approvals)
        self.assertIn("Q2 Strategy", approvals)
        # 由於 replay 成功且 candidate 已 sandbox_verified，按鈕應該是啟用的
        self.assertIn("批准並套用", approvals)
        self.assertNotIn("先完成 replay", approvals)


if __name__ == "__main__":
    unittest.main()
