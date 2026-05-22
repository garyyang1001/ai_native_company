from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .demo import SAFE_PATCH
from .engine import KernelEngine
from .store import KernelStore
from .views import render_approvals_view, render_event_detail_view, render_events_view, render_improvements_view


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: str


def build_demo_store() -> KernelStore:
    store = KernelStore.in_memory()
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


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    store = build_demo_store()

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
    return server


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


if __name__ == "__main__":
    server = serve()
    host, port = server.server_address
    print(f"Closed Loop Kernel prototype UI: http://{host}:{port}/events")
    server.serve_forever()
