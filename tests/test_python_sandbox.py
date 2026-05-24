import os
import sys
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
        self.assertTrue(result.sandbox_env["isolated_mode"])
        self.assertEqual(result.sandbox_env["rlimit_cpu_seconds"], 5)
        self.assertEqual(result.sandbox_env["rlimit_memory_mb"], 256)

    def test_subprocess_sandbox_kills_infinite_loop_via_cpu_rlimit(self):
        sandbox = PythonSandbox(timeout_seconds=1)

        result = sandbox.run_function(
            "def burn():\n    while True:\n        pass\n",
            function_name="burn",
        )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error_message)
        lowered = result.error_message.lower()
        self.assertTrue(
            "sigxcpu" in lowered or "timed out" in lowered or "killed" in lowered,
            f"unexpected error_message: {result.error_message!r}",
        )

    def test_subprocess_sandbox_does_not_inherit_parent_environment(self):
        # 父行程設定一個探針變數；沙盒子行程理論上看不見它。
        # 注意：AST lint 直接擋 `import os`，所以候選只能透過 eval + __import__ 繞道讀環境變數。
        # 這個測試專門驗證「即使 lint 被繞過，環境變數仍然不會洩漏」的第二道防線。
        os.environ["CLK_SANDBOX_LEAK_PROBE"] = "should-not-be-visible"
        self.addCleanup(os.environ.pop, "CLK_SANDBOX_LEAK_PROBE", None)
        sandbox = PythonSandbox()

        result = sandbox.run_function(
            "def probe():\n"
            "    return eval(\"__import__('os').environ.get('CLK_SANDBOX_LEAK_PROBE', 'absent')\")\n",
            function_name="probe",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result, "absent")

    @unittest.skipUnless(sys.platform.startswith("linux"), "RLIMIT_AS only reliably enforced on Linux")
    def test_subprocess_sandbox_blocks_memory_blowup_via_rlimit_as(self):
        sandbox = PythonSandbox(max_memory_mb=64)

        result = sandbox.run_function(
            "def hog():\n    big = bytearray(512 * 1024 * 1024)\n    return len(big)\n",
            function_name="hog",
        )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error_message)
        self.assertTrue(
            "memory" in result.error_message.lower() or "killed" in result.error_message.lower(),
            f"unexpected error_message: {result.error_message!r}",
        )

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
