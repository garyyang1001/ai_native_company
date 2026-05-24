from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import SecurityError


DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_MAX_MEMORY_MB = 256
DEFAULT_MAX_FILE_WRITE_BYTES = 1024
DEFAULT_MAX_SUBPROCESSES = 32

# stdout 上限：避免惡意/失控 candidate 透過 print 灌爆 capture buffer。
DEFAULT_MAX_STDOUT_BYTES = 1_000_000


@dataclass(frozen=True)
class SandboxResult:
    status: str
    result: Any = None
    error_message: str | None = None
    sandbox_env: dict[str, Any] | None = None


class PythonSandbox:
    def __init__(
        self,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
        max_file_write_bytes: int = DEFAULT_MAX_FILE_WRITE_BYTES,
        max_subprocesses: int = DEFAULT_MAX_SUBPROCESSES,
        max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.max_file_write_bytes = max_file_write_bytes
        self.max_subprocesses = max_subprocesses
        self.max_stdout_bytes = max_stdout_bytes

    def run_function(self, source: str, function_name: str, args: list[Any] | None = None) -> SandboxResult:
        validate_python_source(source)
        sandbox_env = self._describe_env()
        with tempfile.TemporaryDirectory(prefix="clk-python-sandbox-") as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate_patch.py"
            runner_path = tmp_path / "runner.py"
            candidate_path.write_text(source, encoding="utf-8")
            runner_path.write_text(_runner_source(), encoding="utf-8")

            popen_kwargs: dict[str, Any] = {
                "cwd": str(tmp_path),
                "text": True,
                "capture_output": True,
                "timeout": self.timeout_seconds + 2,
                "check": False,
                "env": _isolated_env(),
            }
            if sys.platform != "win32":
                popen_kwargs["preexec_fn"] = _build_preexec(
                    cpu_seconds=self.timeout_seconds,
                    max_memory_mb=self.max_memory_mb,
                    max_file_write_bytes=self.max_file_write_bytes,
                    max_subprocesses=self.max_subprocesses,
                )

            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(runner_path),
                        str(candidate_path),
                        function_name,
                        json.dumps(args or []),
                    ],
                    **popen_kwargs,
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(
                    status="failed",
                    error_message=(
                        f"sandbox timed out after {self.timeout_seconds}s "
                        "(wall clock; CPU rlimit should have fired first)"
                    ),
                    sandbox_env=sandbox_env,
                )

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            hint = _interpret_nonzero_exit(proc.returncode, stderr, stdout, self.timeout_seconds, self.max_memory_mb)
            return SandboxResult(status="failed", error_message=hint, sandbox_env=sandbox_env)

        stdout = proc.stdout or ""
        if len(stdout.encode("utf-8")) > self.max_stdout_bytes:
            return SandboxResult(
                status="failed",
                error_message=f"sandbox stdout exceeded {self.max_stdout_bytes} bytes; refused to parse",
                sandbox_env=sandbox_env,
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return SandboxResult(
                status="failed",
                error_message=f"invalid sandbox JSON: {exc}; first 200 chars: {stdout[:200]!r}",
                sandbox_env=sandbox_env,
            )
        if payload.get("status") == "success":
            return SandboxResult(status="success", result=payload.get("result"), sandbox_env=sandbox_env)
        return SandboxResult(
            status="failed",
            error_message=payload.get("error_message", "sandbox failed"),
            sandbox_env=sandbox_env,
        )

    def _describe_env(self) -> dict[str, Any]:
        return {
            "sandbox_type": "python-subprocess",
            "python": sys.version.split()[0],
            "isolated_mode": True,
            "rlimit_cpu_seconds": self.timeout_seconds,
            "rlimit_memory_mb": self.max_memory_mb,
            "rlimit_file_write_bytes": self.max_file_write_bytes,
            "rlimit_subprocesses": self.max_subprocesses,
            "supports_preexec": sys.platform != "win32",
        }


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


def _isolated_env() -> dict[str, str]:
    # 不繼承呼叫者的整個 environ；只保留沙盒運作所需的最小集合。
    base = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }
    # macOS 上 Python 解譯器有時需要 HOME 才能找 frameworks；給它一個空目錄等效值。
    if sys.platform == "darwin":
        base["HOME"] = "/tmp"
    return base


def _build_preexec(cpu_seconds: int, max_memory_mb: int, max_file_write_bytes: int, max_subprocesses: int):
    def _apply():
        import resource  # POSIX only — 在 child process 內 import 即可

        # CPU 軟限制：超過會收到 SIGXCPU；硬限制再多 1 秒給 cleanup。
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))

        # 虛擬位址空間上限（位元組）；macOS 上 RLIMIT_AS 可能被忽略，Linux 上會嚴格生效。
        mem_bytes = max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass

        # 任一檔案的寫入大小上限；只影響 regular file，pipe/stdout 不受限。
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_write_bytes, max_file_write_bytes))
        except (ValueError, OSError):
            pass

        # 限制 fork/spawn；macOS 對 RLIMIT_NPROC 支援不完整，失敗就忽略。
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (max_subprocesses, max_subprocesses))
        except (ValueError, OSError, AttributeError):
            pass

        # 不允許 core dump，避免大檔案落地。
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

        # 從新的 process group 開，方便外層在 timeout 時整組砍掉。
        try:
            os.setsid()
        except OSError:
            pass

    return _apply


def _interpret_nonzero_exit(returncode: int, stderr: str, stdout: str, timeout_seconds: int, max_memory_mb: int) -> str:
    # POSIX 慣例：負數 returncode 是被訊號終止；正數是程式自己 exit。
    if returncode < 0:
        signal_num = -returncode
        if signal_num == 9:  # SIGKILL
            return f"sandbox killed by SIGKILL (likely OOM; rlimit_memory_mb={max_memory_mb})"
        if signal_num == 24:  # SIGXCPU
            return f"sandbox exceeded CPU rlimit ({timeout_seconds}s); killed by SIGXCPU"
        return f"sandbox killed by signal {signal_num}"
    if "MemoryError" in stderr:
        return f"sandbox raised MemoryError (rlimit_memory_mb={max_memory_mb})"
    return stderr or stdout or f"subprocess exited {returncode}"


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
