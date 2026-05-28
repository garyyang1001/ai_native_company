"""Token-leak guard tests for op_assistant_telegram_setwebhook.

Codex Phase 1 review A2: ``raise_for_status`` traceback could leak the bot
token via the URL. The script wraps requests in try/except + raise from None,
and prints everything through ``_sanitize``.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def _load_setwebhook_module():
    path = Path(REPO) / "scripts" / "op_assistant" / "op_assistant_telegram_setwebhook.py"
    spec = importlib.util.spec_from_file_location("op_set_webhook_mod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setmod = _load_setwebhook_module()

FAKE_TOKEN = "123456789:AAA-FAKE-TOKEN-DO-NOT-LEAK-aaaaaaaaa"


class SanitizeTests(unittest.TestCase):
    def test_strips_token_from_url(self) -> None:
        leaked = f"https://api.telegram.org/bot{FAKE_TOKEN}/setWebhook returned 400"
        self.assertEqual(
            setmod._sanitize(leaked),
            "https://api.telegram.org/bot<REDACTED>/setWebhook returned 400",
        )
        self.assertNotIn(FAKE_TOKEN, setmod._sanitize(leaked))

    def test_strips_token_in_traceback_like_string(self) -> None:
        leaked = (
            "requests.exceptions.HTTPError: 400 for url: "
            f"https://api.telegram.org/bot{FAKE_TOKEN}/setWebhook"
        )
        self.assertNotIn(FAKE_TOKEN, setmod._sanitize(leaked))


class SetWebhookErrorPathTests(unittest.TestCase):
    def test_request_exception_does_not_leak_token(self) -> None:
        import requests
        url = f"https://api.telegram.org/bot{FAKE_TOKEN}/setWebhook"

        class _FakeResp:
            status_code = 401

            def raise_for_status(self) -> None:
                err = requests.exceptions.HTTPError(
                    f"401 Client Error: Unauthorized for url: {url}",
                    response=self,   # type: ignore[arg-type]
                )
                raise err

        with patch("requests.post", return_value=_FakeResp()):
            with self.assertRaises(RuntimeError) as ctx:
                setmod._set_webhook(FAKE_TOKEN, "https://example.invalid/x", "secret")
        # The RuntimeError must not echo the URL with the token.
        msg = str(ctx.exception)
        self.assertNotIn(FAKE_TOKEN, msg)
        self.assertIn("setWebhook failed", msg)
        self.assertIn("status=401", msg)
        # And the chained traceback must be suppressed (raise from None).
        self.assertIsNone(ctx.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
