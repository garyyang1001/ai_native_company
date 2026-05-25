"""Unit tests for line_client: signature verification + event parsing.

Signature path is security-critical — wrong implementation lets any caller
spoof LINE webhooks and trigger agent actions. Test round-trip, tampering,
and edge cases (missing/empty headers, wrong secret).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest

from wannavegtour.line_client import (
    LineAPIError,
    parse_events,
    verify_signature,
)


def _sign(body: bytes, secret: str) -> str:
    """Helper: produce the signature header value LINE would send."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


class TestVerifySignature(unittest.TestCase):

    def test_valid_signature(self):
        body = b'{"events":[]}'
        secret = "FIXTURE-not-a-real-secret"  # gitleaks:allow
        sig = _sign(body, secret)
        self.assertTrue(verify_signature(body, sig, secret))

    def test_tampered_body_fails(self):
        secret = "FIXTURE-not-a-real-secret"  # gitleaks:allow
        sig = _sign(b'{"events":[]}', secret)
        tampered = b'{"events":[{"type":"injected"}]}'
        self.assertFalse(verify_signature(tampered, sig, secret))

    def test_wrong_secret_fails(self):
        body = b'{"events":[]}'
        sig = _sign(body, "real_secret")
        self.assertFalse(verify_signature(body, sig, "wrong_secret"))

    def test_missing_signature(self):
        body = b'{"events":[]}'
        self.assertFalse(verify_signature(body, "", "secret"))
        self.assertFalse(verify_signature(body, None, "secret"))  # type: ignore[arg-type]

    def test_missing_secret(self):
        body = b'{"events":[]}'
        sig = _sign(body, "secret")
        self.assertFalse(verify_signature(body, sig, ""))

    def test_empty_body(self):
        body = b""
        secret = "secret"
        sig = _sign(body, secret)
        self.assertTrue(verify_signature(body, sig, secret))

    def test_unicode_body(self):
        # LINE messages contain CJK — make sure we sign the raw bytes, not decoded text.
        body = '{"events":[{"text":"3/5 江南還收嗎"}]}'.encode("utf-8")
        secret = "secret"
        sig = _sign(body, secret)
        self.assertTrue(verify_signature(body, sig, secret))


class TestParseEvents(unittest.TestCase):

    def test_text_message_in_group(self):
        body = json.dumps({
            "events": [{
                "type": "message",
                "timestamp": 1716624000000,
                "replyToken": "rt_test_abc",
                "source": {"type": "group", "groupId": "Cgroup123", "userId": "Uuser456"},
                "message": {"id": "msg_001", "type": "text", "text": "3/5 江南還收嗎"},
            }]
        }).encode("utf-8")
        events = parse_events(body)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "message")
        self.assertEqual(ev.message_type, "text")
        self.assertEqual(ev.text, "3/5 江南還收嗎")
        self.assertEqual(ev.group_id, "Cgroup123")
        self.assertEqual(ev.user_id, "Uuser456")
        self.assertEqual(ev.reply_token, "rt_test_abc")
        self.assertEqual(ev.message_id, "msg_001")
        self.assertFalse(ev.mention_is_self)

    def test_mention_is_self_detected(self):
        body = json.dumps({
            "events": [{
                "type": "message",
                "timestamp": 1716624000000,
                "replyToken": "rt",
                "source": {"type": "group", "groupId": "Cg", "userId": "Uu"},
                "message": {
                    "id": "m1", "type": "text", "text": "@hermes 查一下",
                    "mention": {"mentionees": [
                        {"index": 0, "length": 7, "isSelf": True, "userId": "Uself"}
                    ]},
                },
            }]
        }).encode("utf-8")
        events = parse_events(body)
        self.assertTrue(events[0].mention_is_self)

    def test_mention_by_other_not_self(self):
        body = json.dumps({
            "events": [{
                "type": "message", "timestamp": 1, "replyToken": "rt",
                "source": {"type": "group", "groupId": "Cg", "userId": "Uu"},
                "message": {
                    "id": "m1", "type": "text", "text": "@alice 看一下",
                    "mention": {"mentionees": [
                        {"index": 0, "length": 6, "isSelf": False, "userId": "Ualice"}
                    ]},
                },
            }]
        }).encode("utf-8")
        self.assertFalse(parse_events(body)[0].mention_is_self)

    def test_non_message_event_join(self):
        body = json.dumps({
            "events": [{
                "type": "join", "timestamp": 1,
                "source": {"type": "group", "groupId": "Cgnew"},
                "replyToken": "rt_join",
            }]
        }).encode("utf-8")
        events = parse_events(body)
        self.assertEqual(events[0].event_type, "join")
        self.assertIsNone(events[0].message_type)
        self.assertIsNone(events[0].text)
        self.assertEqual(events[0].group_id, "Cgnew")

    def test_multiple_events(self):
        body = json.dumps({"events": [
            {"type": "message", "timestamp": 1, "source": {"type": "user", "userId": "U1"},
             "message": {"id": "1", "type": "text", "text": "hi"}},
            {"type": "message", "timestamp": 2, "source": {"type": "user", "userId": "U2"},
             "message": {"id": "2", "type": "text", "text": "bye"}},
        ]}).encode("utf-8")
        self.assertEqual(len(parse_events(body)), 2)

    def test_invalid_json_raises(self):
        with self.assertRaises(LineAPIError):
            parse_events(b"{not json}")

    def test_non_object_root_raises(self):
        with self.assertRaises(LineAPIError):
            parse_events(b"[1,2,3]")

    def test_missing_events_key_returns_empty(self):
        events = parse_events(b'{"otherKey": []}')
        self.assertEqual(events, [])

    def test_image_message_has_no_text(self):
        body = json.dumps({"events": [{
            "type": "message", "timestamp": 1, "replyToken": "rt",
            "source": {"type": "group", "groupId": "Cg", "userId": "Uu"},
            "message": {"id": "m1", "type": "image"},
        }]}).encode("utf-8")
        ev = parse_events(body)[0]
        self.assertEqual(ev.message_type, "image")
        self.assertIsNone(ev.text)


if __name__ == "__main__":
    unittest.main()
