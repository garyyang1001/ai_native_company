"""LINE webhook listener — stdlib threading HTTP server.

Receives LINE Messaging API webhook POSTs, verifies x-line-signature, returns
200 within 5s (mandatory or LINE marks delivery failed), then dispatches each
event to the router in a worker thread. Reply / push happens off the request
thread so HTTP response is never blocked by WC API latency.

Endpoints:
    POST /wannavegtour/line/webhook   — main webhook intake
    GET  /healthz                     — liveness check (for Tailscale Funnel)
    GET  /                            — minimal banner

Audit log: append-only JSONL at ~/.hermes/line_events/wannavegtour.jsonl
(per-line one event + dispatch result + timing). Rotation / cleanup is the
event-store layer's job (Q1b storage design, future work).

CLI:
    python3 -m wannavegtour.line_listener [--host 0.0.0.0] [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .availability_checker import AvailabilityChecker
from .config import CredentialError, load_config, load_line_config
from .historical_lookup import HistoricalLookup
from .line_client import (
    LineAPIError,
    LineClient,
    LineEvent,
    parse_events,
    verify_signature,
)
from .line_router import DispatchAction, DispatchResult, LineRouter
from .wc_client import WCClient


# Default endpoint path. LINE webhook URL will be:
#   https://<tailnet>/wannavegtour/line/webhook
WEBHOOK_PATH = "/wannavegtour/line/webhook"
HEALTH_PATH = "/healthz"

# Default audit log location (per-site JSONL).
AUDIT_LOG_DIR = Path.home() / ".hermes" / "line_events"
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "wannavegtour.jsonl"

# Max request body size — protects against memory-exhaustion attacks.
# Real LINE webhooks are typically < 10 KB; we cap generously at 1 MB.
MAX_BODY_BYTES = 1_000_000

# Per-request socket timeout — bounds the body read window so a slowloris-style
# client cannot tie up a request thread by trickling bytes before the signature
# gate runs. Real LINE webhook delivery is well under 1 second; 5 seconds is
# generous and matches the response budget LINE itself enforces on us.
SOCKET_READ_TIMEOUT_SECONDS = 5.0


log = logging.getLogger("wannavegtour.line_listener")


class _ListenerState:
    """Shared state injected into the request handler.

    Built once at server start, accessed concurrently by request threads.
    All fields are either immutable or thread-safe operations only.
    """

    def __init__(
        self, *, router: LineRouter, line_client: LineClient, channel_secret: str,
        audit_path: Path | None = None,
    ) -> None:
        self.router = router
        self.line_client = line_client
        self.channel_secret = channel_secret
        self.audit_path = audit_path or AUDIT_LOG_FILE
        self._audit_lock = threading.Lock()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def audit(self, record: dict) -> None:
        """Append-only JSONL audit. One write per dispatched event."""
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._audit_lock:
            try:
                with self.audit_path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except OSError as e:
                log.error("failed to write audit log: %s", e)


def _build_handler(state: _ListenerState) -> type[BaseHTTPRequestHandler]:
    """Closure over state so handler class can be subclassed cleanly per server."""

    class Handler(BaseHTTPRequestHandler):

        # Bound the body-read window so unauthenticated callers can't tie up
        # a request thread by trickling bytes pre-signature-verification.
        # BaseHTTPRequestHandler picks this up via setup() → self.connection.settimeout().
        timeout = SOCKET_READ_TIMEOUT_SECONDS

        # Quiet the default access logging — we use structured logging instead.
        def log_message(self, format, *args):  # noqa: A002 (shadow built-in by parent contract)
            log.debug("%s - %s", self.address_string(), format % args)

        # ----- GET -----------------------------------------------------------

        def do_GET(self) -> None:
            if self.path == HEALTH_PATH:
                self._respond_text(200, "ok")
                return
            if self.path in ("/", "/wannavegtour/line/"):
                self._respond_text(
                    200,
                    "wannavegtour LINE listener — POST events to "
                    + WEBHOOK_PATH + "\n",
                )
                return
            self._respond_text(404, "not found")

        # ----- POST ----------------------------------------------------------

        def do_POST(self) -> None:
            if self.path != WEBHOOK_PATH:
                self._respond_text(404, "not found")
                return

            # 1. Read body with size cap.
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                self._respond_text(400, "empty body")
                return
            if content_length > MAX_BODY_BYTES:
                self._respond_text(413, "body too large")
                return
            body = self.rfile.read(content_length)

            # 2. Verify signature. Constant-time compare inside verify_signature.
            sig = self.headers.get("x-line-signature", "")
            if not verify_signature(body, sig, state.channel_secret):
                # Log enough to diagnose without leaking the bad signature value.
                log.warning("invalid x-line-signature for %s (body_len=%d)",
                            self.address_string(), len(body))
                self._respond_text(401, "invalid signature")
                return

            # 3. Parse events. Defensive — return 200 even if payload weird,
            #    so LINE doesn't retry a fundamentally broken event forever.
            try:
                events = parse_events(body)
            except Exception as e:  # parse_events can raise LineAPIError or others
                log.error("failed to parse LINE webhook body: %s", e)
                self._respond_text(200, "ok")  # tell LINE "received", we'll log internally
                return

            # 4. Respond 200 BEFORE doing work — LINE's 5s budget.
            self._respond_text(200, "ok")

            # 5. Dispatch each event in a worker thread. Errors are logged + audited;
            #    they never bubble back to LINE (request is already closed).
            for ev in events:
                threading.Thread(
                    target=_process_event_safe, args=(state, ev), daemon=True,
                ).start()

        # ----- internals -----------------------------------------------------

        def _respond_text(self, code: int, text: str) -> None:
            payload = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _process_event_safe(state: _ListenerState, event: LineEvent) -> None:
    """Top-level wrapper: catches all exceptions so one bad event doesn't kill
    other in-flight events. Always writes an audit record."""
    started = time.monotonic()
    audit_record: dict = {
        "event_type": event.event_type,
        "message_type": event.message_type,
        "source_type": event.source_type,
        "group_id": event.group_id,
        "user_id": event.user_id,
        "message_id": event.message_id,
        "mention_is_self": event.mention_is_self,
        "text_len": len(event.text or ""),
        # Raw text retained per Q1b 30-day TTL; cleanup is the event-store layer's job.
        "text": event.text,
    }
    try:
        result = state.router.dispatch(event)
        audit_record.update({
            "action": result.action.value,
            "intent": result.intent,
            "worker": result.worker,
            "skip_reason": result.skip_reason,
            "extras": result.audit_extras,
        })
        if result.action == DispatchAction.REPLY:
            _send_reply(state.line_client, result)
        elif result.action == DispatchAction.ALERT_TELEGRAM:
            # Telegram alerting is out of scope for L1 listener; just log.
            # Telegram bridge wiring lives with the future skimm3r918_bot integration.
            log.info("PRICE_EDIT_HINT — telegram alert TODO. text=%r", event.text)
            audit_record["telegram_alert_pending"] = True
    except Exception as e:
        log.exception("dispatch failed for event %r", event)
        audit_record.update({
            "action": "error",
            "error": str(e),
            "traceback": traceback.format_exc()[:2000],
        })
    finally:
        audit_record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        state.audit(audit_record)


def _send_reply(client: LineClient, result: DispatchResult) -> None:
    """Reply via the cheap reply-token path if still valid; else push."""
    if not result.reply_text:
        log.warning("DispatchResult had REPLY action but no reply_text")
        return
    if result.reply_token:
        try:
            client.reply_text(result.reply_token, result.reply_text)
            return
        except LineAPIError as e:
            log.warning("reply-token API failed (token may be expired): %s — falling back to push", e)
    if result.target_id:
        client.push_text(result.target_id, result.reply_text)
    else:
        log.error("no reply_token AND no target_id — message dropped: %r", result.reply_text[:80])


# --- assembly + CLI ---------------------------------------------------------

def build_state() -> _ListenerState:
    """Wire all dependencies. Loads both credential files (fail-closed on perms)."""
    wc_config = load_config()
    line_config = load_line_config()
    wc_client = WCClient(wc_config)
    line_client = LineClient(line_config)
    router = LineRouter(
        line_config=line_config,
        availability=AvailabilityChecker(wc_client),
        historical=HistoricalLookup(wc_client),
    )
    return _ListenerState(
        router=router, line_client=line_client,
        channel_secret=line_config.channel_secret,
    )


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the listener until SIGTERM / SIGINT."""
    state = build_state()
    handler_cls = _build_handler(state)
    server = ThreadingHTTPServer((host, port), handler_cls)
    log.info("wannavegtour LINE listener on http://%s:%d%s (audit → %s)",
             host, port, WEBHOOK_PATH, state.audit_path)

    def _shutdown(signum, frame):
        log.info("signal %s received — shutting down", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        log.info("listener stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wannavegtour.line_listener")
    parser.add_argument("--host", default=os.environ.get("WANNAVEG_LISTEN_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WANNAVEG_LISTEN_PORT", "8765")))
    parser.add_argument("--log-level", default=os.environ.get("WANNAVEG_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        serve(host=args.host, port=args.port)
    except CredentialError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
