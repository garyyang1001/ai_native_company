"""Thin LINE Messaging API client.

Two responsibilities:
  1. Verify x-line-signature header on inbound webhook POSTs (HMAC-SHA256).
  2. Push messages out to LINE (reply within 30s window, or push to arbitrary groupId).

Mirrors wc_client.py: HTTP + auth + JSON only. No business logic. Failures raise
LineAPIError so callers can map to operational responses.

Constant-time signature comparison (hmac.compare_digest) prevents timing oracles.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from typing import Any

import requests

from .config import LineConfig


# LINE Messaging API: reply tokens expire ~30s after the triggering event.
REPLY_WINDOW_SECONDS = 30

# Max text length per LINE message (5000 chars per official docs).
MAX_TEXT_MESSAGE_LEN = 5000


class LineAPIError(RuntimeError):
    """Raised on any LINE API failure (network, 4xx, 5xx, malformed response)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class LineEvent:
    """Subset of a LINE webhook event we actually use."""
    event_type: str            # "message" / "join" / "leave" / "memberJoined" / "follow" / ...
    message_type: str | None   # "text" / "image" / "sticker" / None for non-message events
    text: str | None
    source_type: str           # "group" / "user" / "room"
    group_id: str | None
    user_id: str | None
    reply_token: str | None    # present on most events; absent on some webhook-only events
    timestamp_ms: int
    message_id: str | None
    mention_is_self: bool      # mention.isSelf for bot-mention awareness (2024-10-30 feature)
    raw: dict[str, Any]


def verify_signature(body: bytes, signature_header: str, channel_secret: str) -> bool:
    """Validate the x-line-signature header.

    LINE computes: base64(HMAC-SHA256(channel_secret, raw_request_body))
    Constant-time comparison via hmac.compare_digest.
    """
    if not signature_header or not channel_secret:
        return False
    try:
        expected_bytes = hmac.new(
            channel_secret.encode("utf-8"), body, hashlib.sha256
        ).digest()
        expected = base64.b64encode(expected_bytes).decode("ascii")
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, signature_header)


def parse_events(body: bytes) -> list[LineEvent]:
    """Parse a LINE webhook POST body into LineEvents. Tolerates partial/missing fields."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise LineAPIError(f"webhook body is not valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise LineAPIError("webhook body is not a JSON object")
    raw_events = payload.get("events") or []
    if not isinstance(raw_events, list):
        raise LineAPIError("webhook body 'events' is not a list")

    out: list[LineEvent] = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        source = ev.get("source") or {}
        message = ev.get("message") or {}
        mention = message.get("mention") if isinstance(message, dict) else None
        mention_is_self = False
        if isinstance(mention, dict):
            for m in (mention.get("mentionees") or []):
                if isinstance(m, dict) and m.get("isSelf"):
                    mention_is_self = True
                    break
        out.append(LineEvent(
            event_type=str(ev.get("type", "")),
            message_type=(str(message.get("type")) if message.get("type") else None),
            text=(message.get("text") if isinstance(message, dict) else None),
            source_type=str(source.get("type", "")),
            group_id=source.get("groupId"),
            user_id=source.get("userId"),
            reply_token=ev.get("replyToken"),
            timestamp_ms=int(ev.get("timestamp", 0) or 0),
            message_id=(str(message.get("id")) if isinstance(message, dict) and message.get("id") else None),
            mention_is_self=mention_is_self,
            raw=ev,
        ))
    return out


class LineClient:
    """Pushes messages back to LINE. Reply API is fast-path (no quota); push is fallback.

    Thread-safety: the underlying requests.Session and urllib3 PoolManager are
    documented thread-safe for read-only session attributes (we never mutate
    headers/auth post-init), but to be explicit and to defuse the "shared
    Session across worker threads" concern raised by code review, every outbound
    HTTP call acquires _send_lock first. Contention is negligible at LINE
    webhook volumes (single-digit messages per second worst case).
    """

    DEFAULT_TIMEOUT = 10

    def __init__(self, config: LineConfig, timeout: float | None = None) -> None:
        self.config = config
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._send_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {config.channel_access_token}",
            "Content-Type": "application/json",
        })

    def reply_text(self, reply_token: str, text: str) -> None:
        """Use the reply-token API (no quota cost). Must be called within 30s of event.

        Raises LineAPIError on HTTP non-2xx or network failure.
        """
        text = self._truncate(text)
        url = f"{self.config.api_root}/v2/bot/message/reply"
        body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
        self._post(url, body)

    def push_text(self, to: str, text: str) -> None:
        """Push to a user / group / room id (counts toward monthly quota)."""
        text = self._truncate(text)
        url = f"{self.config.api_root}/v2/bot/message/push"
        body = {"to": to, "messages": [{"type": "text", "text": text}]}
        self._post(url, body)

    def get_bot_info(self) -> dict[str, Any]:
        """Smoke-test endpoint: verifies token is valid + reports bot identity."""
        url = f"{self.config.api_root}/v2/bot/info"
        try:
            with self._send_lock:
                r = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise LineAPIError(f"network error reaching {url}: {e}") from e
        if r.status_code != 200:
            raise LineAPIError(f"HTTP {r.status_code} from {url}: {r.text[:200]}", r.status_code)
        try:
            return r.json()
        except ValueError as e:
            raise LineAPIError(f"non-JSON response from {url}: {r.text[:200]}") from e

    # --- internals ----------------------------------------------------------

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) > MAX_TEXT_MESSAGE_LEN:
            # LINE silently rejects oversized; truncate + mark.
            return text[: MAX_TEXT_MESSAGE_LEN - 20] + "\n…(訊息已截斷)"
        return text

    def _post(self, url: str, body: dict[str, Any]) -> None:
        try:
            with self._send_lock:
                r = self._session.post(url, data=json.dumps(body), timeout=self.timeout)
        except requests.RequestException as e:
            raise LineAPIError(f"network error reaching {url}: {e}") from e
        if r.status_code >= 400:
            raise LineAPIError(f"HTTP {r.status_code} from {url}: {r.text[:200]}", r.status_code)
