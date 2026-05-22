from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import SecurityError


@dataclass(frozen=True)
class SandboxResult:
    status: str
    result: Any = None
    error_message: str | None = None
    sandbox_env: dict[str, Any] | None = None


class PythonSandbox:
    def __init__(self, timeout_seconds: int = 5):
        self.timeout_seconds = timeout_seconds

    def run_function(self, source: str, function_name: str, args: list[Any] | None = None) -> SandboxResult:
        validate_python_source(source)
        with tempfile.TemporaryDirectory(prefix="clk-python-sandbox-") as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate_patch.py"
            runner_path = tmp_path / "runner.py"
            candidate_path.write_text(source, encoding="utf-8")
            runner_path.write_text(_runner_source(), encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(runner_path),
                    str(candidate_path),
                    function_name,
                    json.dumps(args or []),
                ],
                cwd=str(tmp_path),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )

        sandbox_env = {"sandbox_type": "python-subprocess", "python": sys.version.split()[0]}
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or f"subprocess exited {proc.returncode}"
            return SandboxResult(status="failed", error_message=message, sandbox_env=sandbox_env)

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return SandboxResult(status="failed", error_message=f"invalid sandbox JSON: {exc}", sandbox_env=sandbox_env)
        if payload.get("status") == "success":
            return SandboxResult(status="success", result=payload.get("result"), sandbox_env=sandbox_env)
        return SandboxResult(status="failed", error_message=payload.get("error_message", "sandbox failed"), sandbox_env=sandbox_env)


def validate_python_source(source: str) -> None:
    forbidden_names = {"os", "sys", "subprocess", "socket", "shutil"}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SecurityError(f"Python AST Lint Blocked: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden_names:
                    raise SecurityError("Python AST Lint Blocked: Forbidden module import")
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden_names:
            raise SecurityError("Python AST Lint Blocked: Forbidden module import")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "__import__"}:
            raise SecurityError("Python AST Lint Blocked: Forbidden function call")


def _runner_source() -> str:
    return r'''
import importlib.util
import json
import sys
import traceback

module_path, function_name, args_json = sys.argv[1:4]
args = json.loads(args_json)

try:
    spec = importlib.util.spec_from_file_location("candidate_patch", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, function_name)
    result = fn(*args)
    print(json.dumps({"status": "success", "result": result}, ensure_ascii=False))
except Exception:
    print(json.dumps({"status": "failed", "error_message": traceback.format_exc()}, ensure_ascii=False))
'''
