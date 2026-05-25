"""Tests for line_listener HTTP handler.

Spins up the real ThreadingHTTPServer on an ephemeral port with mocked
state — verifies signature gate, health endpoints, and the listener's
"always 200 before work" contract.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import requests

from wannavegtour.line_client import LineClient
from wannavegtour.line_listener import HEALTH_PATH, WEBHOOK_PATH, _build_handler, _ListenerState
from wannavegtour.line_router import DispatchAction, DispatchResult, LineRouter


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _make_server(state: _ListenerState) -> tuple[ThreadingHTTPServer, str, threading.Thread]:
    handler = _build_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # 0 = ephemeral
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, base_url, thread


class TestListener(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._audit = Path(cls._tmpdir.name) / "audit.jsonl"

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        self.router = MagicMock(spec=LineRouter)
        self.router.dispatch.return_value = DispatchResult(
            action=DispatchAction.SILENT, intent="availability_check",
            worker="availability_checker", skip_reason="testing",
        )
        self.line_client = MagicMock(spec=LineClient)
        self.secret = "test_channel_secret"
        # Wipe audit file between tests so assertions are deterministic.
        if self._audit.exists():
            self._audit.unlink()
        self.state = _ListenerState(
            router=self.router, line_client=self.line_client,
            channel_secret=self.secret, audit_path=self._audit,
        )
        self.server, self.base_url, self.thread = _make_server(self.state)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    # ----- health endpoints -------------------------------------------------

    def test_healthz_returns_200(self):
        r = requests.get(f"{self.base_url}{HEALTH_PATH}", timeout=2)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")

    def test_root_returns_banner(self):
        r = requests.get(f"{self.base_url}/", timeout=2)
        self.assertEqual(r.status_code, 200)
        self.assertIn(WEBHOOK_PATH, r.text)

    def test_unknown_path_404(self):
        r = requests.get(f"{self.base_url}/nope", timeout=2)
        self.assertEqual(r.status_code, 404)

    # ----- POST signature gate ---------------------------------------------

    def test_valid_signed_post_returns_200(self):
        body = json.dumps({"events": []}).encode("utf-8")
        sig = _sign(body, self.secret)
        r = requests.post(
            f"{self.base_url}{WEBHOOK_PATH}",
            data=body,
            headers={"x-line-signature": sig, "Content-Type": "application/json"},
            timeout=2,
        )
        self.assertEqual(r.status_code, 200)

    def test_invalid_signature_returns_401(self):
        body = json.dumps({"events": []}).encode("utf-8")
        r = requests.post(
            f"{self.base_url}{WEBHOOK_PATH}",
            data=body,
            headers={"x-line-signature": "wrong_sig", "Content-Type": "application/json"},
            timeout=2,
        )
        self.assertEqual(r.status_code, 401)
        self.router.dispatch.assert_not_called()  # work must NOT happen

    def test_missing_signature_returns_401(self):
        body = json.dumps({"events": []}).encode("utf-8")
        r = requests.post(
            f"{self.base_url}{WEBHOOK_PATH}",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=2,
        )
        self.assertEqual(r.status_code, 401)

    def test_oversized_body_returns_413(self):
        body = b"x" * 2_000_000   # > MAX_BODY_BYTES
        sig = _sign(body, self.secret)
        # Note: server might not even read the body — 413 should be returned based on Content-Length
        try:
            r = requests.post(
                f"{self.base_url}{WEBHOOK_PATH}",
                data=body,
                headers={"x-line-signature": sig, "Content-Type": "application/json"},
                timeout=5,
            )
            self.assertEqual(r.status_code, 413)
        except requests.exceptions.RequestException:
            # If server closes the connection on oversized, that's also acceptable.
            pass

    # ----- dispatch behavior -----------------------------------------------

    def test_signed_post_dispatches_to_router(self):
        body = json.dumps({
            "events": [{
                "type": "message", "timestamp": 1, "replyToken": "rt",
                "source": {"type": "group", "groupId": "Cg", "userId": "Uu"},
                "message": {"id": "m1", "type": "text", "text": "3/5 江南"},
            }]
        }).encode("utf-8")
        sig = _sign(body, self.secret)
        r = requests.post(
            f"{self.base_url}{WEBHOOK_PATH}", data=body,
            headers={"x-line-signature": sig}, timeout=2,
        )
        self.assertEqual(r.status_code, 200)
        # Give the worker thread time to fire.
        time.sleep(0.5)
        self.router.dispatch.assert_called_once()

    def test_handler_has_socket_timeout_set(self):
        """Codex review 2026-05-25 P1: handler must set a bounded socket
        timeout so slowloris-style clients can't tie up request threads
        before signature verification."""
        from wannavegtour.line_listener import SOCKET_READ_TIMEOUT_SECONDS, _build_handler
        handler_cls = _build_handler(self.state)
        # BaseHTTPRequestHandler.setup() calls self.connection.settimeout(self.timeout).
        # Verifying the class attribute is set is the deterministic test.
        self.assertIsNotNone(handler_cls.timeout)
        self.assertLessEqual(handler_cls.timeout, 10.0,
                             "socket timeout must be ≤ 10s to bound slowloris attacks")
        self.assertEqual(handler_cls.timeout, SOCKET_READ_TIMEOUT_SECONDS)

    def test_audit_log_written(self):
        body = json.dumps({
            "events": [{
                "type": "message", "timestamp": 1, "replyToken": "rt",
                "source": {"type": "group", "groupId": "Cg", "userId": "Uu"},
                "message": {"id": "m1", "type": "text", "text": "3/5 江南"},
            }]
        }).encode("utf-8")
        sig = _sign(body, self.secret)
        requests.post(
            f"{self.base_url}{WEBHOOK_PATH}", data=body,
            headers={"x-line-signature": sig}, timeout=2,
        )
        time.sleep(0.5)
        self.assertTrue(self._audit.exists())
        lines = self._audit.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event_type"], "message")
        self.assertEqual(record["text"], "3/5 江南")
        self.assertIn("elapsed_ms", record)


if __name__ == "__main__":
    unittest.main()
