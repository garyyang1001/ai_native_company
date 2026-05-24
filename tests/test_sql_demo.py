import os
import unittest

from closed_loop_kernel.sql_demo import run_sql_demo


@unittest.skipUnless(
    os.environ.get("KERNEL_DATABASE_URL") and os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET") == "1",
    "sql_demo requires KERNEL_DATABASE_URL and KERNEL_ALLOW_DESTRUCTIVE_RESET=1",
)
class SqlDemoTests(unittest.TestCase):
    def test_run_sql_demo_completes_scenario_one_loop(self):
        result = run_sql_demo()

        # 失敗的 attempt 仍是 failed（不可篡改）；retry attempt 成功
        attempt_history = result["attempt_history"]
        self.assertEqual(len(attempt_history), 2)
        self.assertEqual(attempt_history[0]["status"], "failed")
        self.assertIn("document_tags", attempt_history[0]["error_message"])
        self.assertEqual(attempt_history[1]["status"], "success")

        # candidate / failure / replay 最終狀態
        self.assertEqual(result["candidate_status"], "applied")
        self.assertEqual(result["failure_status"], "resolved")
        self.assertEqual(result["replay_status"], "success")
        self.assertTrue(result["replay_sandbox_schema"].startswith("sandbox_temp_"))

        # 部署後 active artifact 應指向修正後的 SQL
        self.assertIn("document_tags_mapping", result["active_artifact_content"])
        self.assertNotIn(
            " document_tags ", " " + result["active_artifact_content"] + " ",
            "active SQL should no longer reference the wrong table",
        )


if __name__ == "__main__":
    unittest.main()
