from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from urllib.parse import unquote, urlparse

from .demo import SAFE_PATCH
from .engine import KernelEngine
from .store import RESET_CONFIRMATION, KernelStore
from .views import render_approvals_view, render_event_detail_view, render_events_view, render_improvements_view


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: str


def seed_demo_store() -> KernelStore:
    """
    重置目標 DB 並塞入 Scenario 2 (code_patch) 種子資料。

    需要 `KERNEL_ALLOW_DESTRUCTIVE_RESET=1`；會 `DROP SCHEMA public CASCADE` 後重建。
    用途：第一次跑 prototype、或刻意要回到乾淨種子狀態時呼叫一次。
    """
    store = KernelStore.from_url(_database_url())
    try:
        _reset_demo_database(store)
        store.initialize()
        engine = KernelEngine(store)

        artifact_id = engine.create_artifact(
            "skills.compute_score",
            "python",
            "def compute_score(base, bonus):\n    return base + bonus\n",
        )
        attempt_id = engine.start_attempt({"skill": "compute_score", "base": 10, "bonus": None})
        engine.finish_attempt(
            attempt_id,
            "failed",
            {"skill": "compute_score", "base": 10, "bonus": None},
            error_message="TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'",
        )
        failure_id = store.scalar("SELECT id FROM failures WHERE attempt_id = ?", [attempt_id])
        candidate_id = engine.propose_improvement(
            failure_id,
            artifact_id,
            "code_patch",
            SAFE_PATCH,
            {"expected_result": 10},
            {"restore_artifact_id": artifact_id},
        )
        engine.replay_code_candidate(candidate_id, function_name="compute_score", args=[10, None])
        return store
    except Exception:
        store.close()
        raise


def open_store() -> KernelStore:
    """
    只連線、不 reset；schema 不存在則建（CREATE TABLE IF NOT EXISTS 是 idempotent）。

    用途：serve 模式下 Gary 想保留先前 demo 的歷史（含 SQL self-healing scenario 跑完
    的記錄）；多次重啟 server 不會把過去 attempts / approvals 清掉。
    """
    store = KernelStore.from_url(_database_url())
    try:
        store.initialize()
        return store
    except Exception:
        store.close()
        raise


def route_request(store: KernelStore, path: str) -> HttpResponse:
    parsed = urlparse(path)
    route = parsed.path.rstrip("/") or "/"
    if route == "/":
        return _redirect_like("/events")
    if route == "/favicon.ico":
        return HttpResponse(204, "image/x-icon", "")
    if route == "/events":
        return _html(render_events_view(store))
    if route.startswith("/events/"):
        attempt_id = unquote(route.split("/", 2)[2])
        return _html(render_event_detail_view(store, attempt_id))
    if route == "/improvements":
        return _html(render_improvements_view(store))
    if route == "/approvals":
        return _html(render_approvals_view(store))
    return HttpResponse(404, "text/html; charset=utf-8", "<h1>Not Found</h1>")


def route_post(store: KernelStore, path: str) -> HttpResponse:
    parsed = urlparse(path)
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) == 3 and parts[0] == "approvals":
        candidate_id, action = parts[1], parts[2]
        engine = KernelEngine(store)
        if action == "approve":
            engine.approve_candidate(candidate_id, "human_dri:gary", "Approved from local prototype UI")
            engine.apply_candidate(candidate_id)
            return _see_other("/approvals", "applied")
        if action == "reject":
            engine.reject_candidate(candidate_id, "human_dri:gary", "Rejected from local prototype UI")
            return _see_other("/approvals", "rejected")
    return HttpResponse(404, "text/html; charset=utf-8", "<h1>Not Found</h1>")


def serve(host: str = "127.0.0.1", port: int = 8765, *, with_seed: bool = False) -> ThreadingHTTPServer:
    """
    啟動 HTTP server。

    預設 `with_seed=False`：不 reset，沿用 DB 既有狀態（如果 schema 不存在會自動建）。
    `with_seed=True`：先 reset + 種 Scenario 2 demo 資料；需要 KERNEL_ALLOW_DESTRUCTIVE_RESET=1。
    """
    store = seed_demo_store() if with_seed else open_store()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            response = route_request(store, self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.end_headers()
            self.wfile.write(response.body.encode("utf-8"))

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            response = route_post(store, self.path)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            if response.status == 303:
                self.send_header("Location", "/approvals")
            self.end_headers()
            self.wfile.write(response.body.encode("utf-8"))

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.kernel_store = store
    return server


def _database_url() -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise RuntimeError("KERNEL_DATABASE_URL is required; kernel runtime is PostgreSQL-only")
    return url


def _reset_demo_database(store: KernelStore) -> None:
    if os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET") != "1":
        raise RuntimeError("KERNEL_ALLOW_DESTRUCTIVE_RESET=1 is required to reset the PostgreSQL demo database")
    store.reset_for_test(confirm=RESET_CONFIRMATION)


def _html(body: str) -> HttpResponse:
    return HttpResponse(200, "text/html; charset=utf-8", body)


def _redirect_like(target: str) -> HttpResponse:
    return HttpResponse(
        200,
        "text/html; charset=utf-8",
        f'<meta http-equiv="refresh" content="0; url={target}"><a href="{target}">Open events</a>',
    )


def _see_other(target: str, message: str) -> HttpResponse:
    return HttpResponse(
        303,
        "text/html; charset=utf-8",
        f'<meta http-equiv="refresh" content="0; url={target}">{message}',
    )


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Closed Loop Kernel prototype HTTP UI",
        epilog=(
            "modes:\n"
            "  serve            (default) 啟動 server，不 reset DB；保留先前歷史。\n"
            "  seed             只 reset + 種 Scenario 2 demo 資料，不啟動 server。\n"
            "  seed-and-serve   reset + seed 後啟動 server；一次性重置 demo 場景。\n"
            "  seed 與 seed-and-serve 都需要 KERNEL_ALLOW_DESTRUCTIVE_RESET=1。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", nargs="?", default="serve", choices=["serve", "seed", "seed-and-serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.mode == "seed":
        store = seed_demo_store()
        try:
            print("Seeded Scenario 2 demo data into KERNEL_DATABASE_URL.")
        finally:
            store.close()
        return

    with_seed = args.mode == "seed-and-serve"
    server = serve(host=args.host, port=args.port, with_seed=with_seed)
    host, port = server.server_address
    seed_note = " (DB was reset + seeded)" if with_seed else " (DB state preserved)"
    print(f"Closed Loop Kernel prototype UI: http://{host}:{port}/events{seed_note}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        server.kernel_store.close()


if __name__ == "__main__":
    _main()
