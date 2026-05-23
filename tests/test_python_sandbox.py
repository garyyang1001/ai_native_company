import unittest

from closed_loop_kernel import KernelEngine, SecurityError
from tests.postgres_test_utils import build_postgres_store
from closed_loop_kernel.sandbox import PythonSandbox


class PythonSandboxTests(unittest.TestCase):
    def test_subprocess_sandbox_runs_safe_function_and_returns_json_result(self):
        sandbox = PythonSandbox()

        result = sandbox.run_function(
            "def compute_score(base, bonus):\n    return base + (bonus or 0)\n",
            function_name="compute_score",
            args=[10, None],
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result, 10)
        self.assertEqual(result.error_message, None)
        self.assertIn("subprocess", result.sandbox_env["sandbox_type"])

    def test_subprocess_sandbox_blocks_unsafe_code_before_execution(self):
        sandbox = PythonSandbox()

        with self.assertRaisesRegex(SecurityError, "Python AST Lint Blocked"):
            sandbox.run_function(
                "import os\n\ndef compute_score(base, bonus):\n    os.system('echo unsafe')\n    return 0\n",
                function_name="compute_score",
                args=[10, None],
            )

    def test_engine_replays_code_candidate_and_marks_it_sandbox_verified(self):
        store = build_postgres_store()
        self.addCleanup(store.close)
        engine = KernelEngine(store)
        artifact_id = engine.create_artifact(
            "skills.compute_score",
            "python",
            "def compute_score(base, bonus):\n    return base + bonus\n",
        )
        failure_id = engine.create_failure_for_test("TypeError")
        candidate_id = engine.propose_improvement(
            failure_id,
            artifact_id,
            "code_patch",
            "def compute_score(base, bonus):\n    return base + (bonus or 0)\n",
            {"expected_result": 10},
            {"restore_artifact_id": artifact_id},
        )

        replay_id = engine.replay_code_candidate(candidate_id, function_name="compute_score", args=[10, None])

        replay = store.fetch_one("SELECT * FROM replays WHERE id = ?", [replay_id])
        self.assertEqual(replay["status"], "success")
        self.assertEqual(store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "sandbox_verified")


if __name__ == "__main__":
    unittest.main()
