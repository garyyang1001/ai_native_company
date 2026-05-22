import unittest

from closed_loop_kernel.demo import run_demo


class DemoTests(unittest.TestCase):
    def test_run_demo_returns_closed_loop_summary(self):
        summary = run_demo()

        self.assertEqual(summary["failed_attempt_status"], "failed")
        self.assertEqual(summary["candidate_status"], "applied")
        self.assertEqual(summary["failure_status"], "resolved")
        self.assertEqual(summary["active_artifact_content"], "def compute_score(base, bonus):\n    return base + (bonus or 0)\n")
        self.assertEqual(summary["blocked_terms"], [])


if __name__ == "__main__":
    unittest.main()
