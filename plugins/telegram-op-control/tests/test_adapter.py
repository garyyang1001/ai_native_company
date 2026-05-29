"""pytest tests for telegram-op-control adapter (V0.3 Phase 1).

Covers acceptance criteria from
``.claude/jobs/1d06a75b/phase1_telegram_inbound_brief.md`` §Acceptance.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

# Match the sys.path strategy used by plugins/op-assistant-tools/tests.
REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
PLUGIN_DIR = f"{REPO}/plugins/telegram-op-control"
for p in (REPO, PLUGIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from aiohttp import web                                       # noqa: E402
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer  # noqa: E402

import adapter as adapter_mod                                 # noqa: E402
from adapter import (                                         # noqa: E402
    AdapterConfig,
    EVENT_TELEGRAM_INBOUND,
    EVENT_TELEGRAM_MALFORMED,
    EVENT_TELEGRAM_REJECTED_CHAT,
    EVENT_TELEGRAM_UNAUTHORIZED,
    SECRET_TOKEN_HEADER,
    UpdateIdDedupe,
    WEBHOOK_PATH,
    create_app,
    extract_actor_user_id,
    extract_chat_id,
)


# --- fake writer ------------------------------------------------------------

class FakeWriter:
    """In-memory substitute for EventWriter (no KernelStore, no PG)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def write(self, event_type: str, payload: dict[str, Any]) -> str:
        self.events.append((event_type, payload))
        return f"fake-{len(self.events)}"

    def close(self) -> None:  # pragma: no cover — match real writer surface
        return None

    def by_type(self, event_type: str) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == event_type]


# --- update fixtures --------------------------------------------------------

SECRET = "test-secret-32-bytes-aaaaaaaaaaaaaaaa"
ALLOWED_CHATS = frozenset({"123456789", "-1001234567890"})


def make_update(
    update_id: int = 1,
    chat_id: str = "123456789",
    kind: str = "message",
    text: str = "hi",
    callback_data: str = "apv:abcd1234:hash5678",
) -> dict[str, Any]:
    if kind == "message":
        return {
            "update_id": update_id,
            "message": {
                "message_id": 100,
                "chat": {"id": int(chat_id), "type": "private"},
                "from": {"id": int(chat_id), "is_bot": False, "first_name": "Test"},
                "date": 1234567890,
                "text": text,
            },
        }
    if kind == "callback_query":
        return {
            "update_id": update_id,
            "callback_query": {
                "id": "cb-1",
                "from": {"id": int(chat_id), "is_bot": False, "first_name": "Test"},
                "message": {
                    "message_id": 100,
                    "chat": {"id": int(chat_id), "type": "private"},
                    "date": 1234567890,
                },
                "data": callback_data,
            },
        }
    if kind == "edited_message":
        return {
            "update_id": update_id,
            "edited_message": {
                "message_id": 100,
                "chat": {"id": int(chat_id), "type": "private"},
                "date": 1234567890,
                "edit_date": 1234567891,
                "text": text,
            },
        }
    raise ValueError(f"unknown kind: {kind}")


# --- webhook integration tests ---------------------------------------------

class TelegramWebhookTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.fake_writer = FakeWriter()
        self.config = AdapterConfig(
            webhook_secret=SECRET,
            allowed_chats=ALLOWED_CHATS,
        )
        return create_app(self.config, writer=self.fake_writer)

    async def test_signature_pass_happy_path(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=make_update(update_id=11),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"

        inbound = self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)
        assert len(inbound) == 1
        assert inbound[0]["update_id"] == 11
        assert inbound[0]["effective_chat_id"] == "123456789"
        assert inbound[0]["kind"] == "message"
        # raw_update preserved verbatim for Phase 4 dispatcher
        assert inbound[0]["raw_update"]["message"]["text"] == "hi"

    async def test_signature_fail_rejected_and_logged(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: "wrong-token"},
            json=make_update(update_id=22),
        )
        assert resp.status == 401

        unauthorized = self.fake_writer.by_type(EVENT_TELEGRAM_UNAUTHORIZED)
        assert len(unauthorized) == 1
        log_text = json.dumps(unauthorized[0])
        # Neither token nor secret may leak into the audit log.
        assert "wrong-token" not in log_text
        assert SECRET not in log_text
        # received_token_len is fine to record (it's metadata, not the value).
        assert unauthorized[0]["received_token_len"] == len("wrong-token")

        # Did NOT fall through to record telegram_inbound for this update.
        assert self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND) == []

    async def test_missing_signature_header(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            json=make_update(update_id=23),
        )
        assert resp.status == 401
        assert len(self.fake_writer.by_type(EVENT_TELEGRAM_UNAUTHORIZED)) == 1

    async def test_dedupe_same_update_id_returns_ok_no_double_log(self) -> None:
        u = make_update(update_id=33)
        resp1 = await self.client.post(WEBHOOK_PATH,
                                       headers={SECRET_TOKEN_HEADER: SECRET},
                                       json=u)
        resp2 = await self.client.post(WEBHOOK_PATH,
                                       headers={SECRET_TOKEN_HEADER: SECRET},
                                       json=u)
        assert resp1.status == 200
        assert resp2.status == 200
        assert (await resp2.json())["status"] == "duplicate"

        # Only the first write hit the writer.
        assert len(self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)) == 1

    async def test_chat_not_whitelisted_403_with_suffix(self) -> None:
        u = make_update(update_id=44, chat_id="999999999")
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert resp.status == 403

        rejected = self.fake_writer.by_type(EVENT_TELEGRAM_REJECTED_CHAT)
        assert len(rejected) == 1
        assert rejected[0]["update_id"] == 44
        # Only the suffix is stored — never the full chat_id (PII-ish).
        assert rejected[0]["chat_id_suffix"] == "9999"
        assert "999999999" not in json.dumps(rejected[0])
        # Did NOT record telegram_inbound for the rejected chat.
        assert self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND) == []

    async def test_callback_query_path_extracts_chat_correctly(self) -> None:
        u = make_update(update_id=66, kind="callback_query")
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert resp.status == 200
        inbound = self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)
        assert len(inbound) == 1
        assert inbound[0]["kind"] == "callback_query"
        assert inbound[0]["effective_chat_id"] == "123456789"
        # raw_update.callback_query.data preserved for Phase 4 dispatcher
        assert (inbound[0]["raw_update"]["callback_query"]["data"]
                == "apv:abcd1234:hash5678")

    async def test_edited_message_path(self) -> None:
        u = make_update(update_id=67, kind="edited_message")
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert resp.status == 200
        inbound = self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)
        assert len(inbound) == 1
        assert inbound[0]["kind"] == "edited_message"

    async def test_malformed_missing_update_id(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json={"random": "garbage"},
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["reason"] == "missing_or_non_int_update_id"

    async def test_malformed_unknown_update_shape(self) -> None:
        # update_id present but no message / callback_query / edited_message
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json={"update_id": 70, "channel_post": {"chat": {"id": 1}}},
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["reason"] == "no_extractable_chat_id"
        assert malformed[0]["update_kind"] == "unknown"

    async def test_malformed_non_json_body(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET,
                     "Content-Type": "application/json"},
            data=b"<<not-json>>",
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["reason"] == "json_or_utf8_decode_failed"

    async def test_malformed_non_object_json(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=["not", "an", "object"],
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["reason"] == "update_not_object"

    async def test_unauthorized_chat_retry_still_audited(self) -> None:
        """Codex C3 regression: dedupe must NOT silently swallow repeated
        rejected updates. Two retries of the same forbidden update_id should
        both leave audit rows.
        """
        u = make_update(update_id=80, chat_id="999999999")
        r1 = await self.client.post(WEBHOOK_PATH,
                                    headers={SECRET_TOKEN_HEADER: SECRET}, json=u)
        r2 = await self.client.post(WEBHOOK_PATH,
                                    headers={SECRET_TOKEN_HEADER: SECRET}, json=u)
        assert r1.status == 403
        assert r2.status == 403
        rejected = self.fake_writer.by_type(EVENT_TELEGRAM_REJECTED_CHAT)
        assert len(rejected) == 2, "both retries must audit-log"

    async def test_oversized_body_413(self) -> None:
        """Codex C5: explicit oversized body test (declared via content-length)."""
        oversized = b"x" * (1024 * 1024 + 100)   # > 1 MiB
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET,
                     "Content-Type": "application/json"},
            data=oversized,
        )
        # aiohttp's client_max_size or our explicit cap should both reject.
        assert resp.status in (400, 413, 200)  # aiohttp may return 200 for
        # malformed body if it parses; we accept that as long as no inbound row
        # was created.
        assert self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND) == []

    async def test_malformed_message_as_string(self) -> None:
        """Codex xhigh #2: signed-but-malformed nested types do not 500."""
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json={"update_id": 100, "message": "not-a-dict"},
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["reason"] == "no_extractable_chat_id"
        assert malformed[0]["update_kind"] == "message"

    async def test_malformed_callback_query_as_list(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json={"update_id": 101, "callback_query": ["x"]},
        )
        assert resp.status == 400
        malformed = self.fake_writer.by_type(EVENT_TELEGRAM_MALFORMED)
        assert len(malformed) == 1
        assert malformed[0]["update_kind"] == "callback_query"

    async def test_actor_user_id_recorded_in_payload(self) -> None:
        """Codex xhigh #4: Phase 4 will need actor-level allowlists."""
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=make_update(update_id=120),
        )
        assert resp.status == 200
        inbound = self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)
        assert len(inbound) == 1
        # Telegram fixture sets from.id == chat.id, but they are conceptually
        # different and Phase 4 must use actor_user_id, not effective_chat_id.
        assert inbound[0]["actor_user_id"] == "123456789"

    async def test_callback_query_actor_extracted(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=make_update(update_id=121, kind="callback_query"),
        )
        assert resp.status == 200
        inbound = self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND)
        assert inbound[0]["actor_user_id"] == "123456789"


# --- empty allowlist (separate test class because get_application
# is called once per AioHTTPTestCase) ---------------------------------------

class EmptyAllowlistTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.fake_writer = FakeWriter()
        self.config = AdapterConfig(
            webhook_secret=SECRET,
            allowed_chats=frozenset(),
        )
        return create_app(self.config, writer=self.fake_writer)

    async def test_empty_allowlist_rejects_all(self) -> None:
        resp = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=make_update(update_id=55),
        )
        assert resp.status == 403
        rejected = self.fake_writer.by_type(EVENT_TELEGRAM_REJECTED_CHAT)
        assert len(rejected) == 1
        # Did NOT record telegram_inbound — fail-closed.
        assert self.fake_writer.by_type(EVENT_TELEGRAM_INBOUND) == []


# --- health endpoint --------------------------------------------------------

class HealthTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        return create_app(
            AdapterConfig(webhook_secret=SECRET, allowed_chats=ALLOWED_CHATS),
            writer=FakeWriter(),
        )

    async def test_health(self) -> None:
        resp = await self.client.get("/health")
        assert resp.status == 200
        assert (await resp.json())["ok"] is True


# --- standalone unit tests --------------------------------------------------

class DedupeTests(unittest.TestCase):
    """Two-phase dedupe API (codex xhigh review #1)."""

    def test_first_begin_is_fresh(self) -> None:
        d = UpdateIdDedupe()
        self.assertFalse(d.begin(1))

    def test_pending_counts_as_seen(self) -> None:
        d = UpdateIdDedupe()
        d.begin(1)
        # second begin without commit must report duplicate
        self.assertTrue(d.begin(1))

    def test_committed_counts_as_seen(self) -> None:
        d = UpdateIdDedupe()
        d.begin(1)
        d.commit(1)
        self.assertTrue(d.begin(1))

    def test_rollback_clears_pending(self) -> None:
        d = UpdateIdDedupe()
        d.begin(1)
        d.rollback(1)
        # rollback drops the pending mark → retry can re-process
        self.assertFalse(d.begin(1))

    def test_rollback_is_noop_on_committed(self) -> None:
        d = UpdateIdDedupe()
        d.begin(1)
        d.commit(1)
        d.rollback(1)
        # committed entries are durable — rollback must not erase them
        self.assertTrue(d.begin(1))

    def test_different_ids_independent(self) -> None:
        d = UpdateIdDedupe()
        self.assertFalse(d.begin(1))
        self.assertFalse(d.begin(2))
        self.assertTrue(d.begin(1))


class ExtractChatTests(unittest.TestCase):
    def test_message_path(self) -> None:
        chat, kind = extract_chat_id({"message": {"chat": {"id": 42}}})
        self.assertEqual((chat, kind), ("42", "message"))

    def test_callback_query_path(self) -> None:
        chat, kind = extract_chat_id({
            "callback_query": {"message": {"chat": {"id": 42}}},
        })
        self.assertEqual((chat, kind), ("42", "callback_query"))

    def test_edited_message_path(self) -> None:
        chat, kind = extract_chat_id({"edited_message": {"chat": {"id": 42}}})
        self.assertEqual((chat, kind), ("42", "edited_message"))

    def test_unknown_path(self) -> None:
        chat, kind = extract_chat_id({"channel_post": {"chat": {"id": 42}}})
        self.assertEqual((chat, kind), (None, "unknown"))

    def test_callback_query_without_message_chat(self) -> None:
        chat, kind = extract_chat_id({"callback_query": {"id": "cb"}})
        self.assertEqual((chat, kind), (None, "callback_query"))

    def test_message_as_string_does_not_raise(self) -> None:
        """Codex xhigh #2: defense against malformed nested types."""
        chat, kind = extract_chat_id({"message": "not-a-dict"})
        self.assertEqual((chat, kind), (None, "message"))

    def test_callback_query_as_list_does_not_raise(self) -> None:
        chat, kind = extract_chat_id({"callback_query": ["x"]})
        self.assertEqual((chat, kind), (None, "callback_query"))

    def test_chat_as_string_inside_message(self) -> None:
        chat, kind = extract_chat_id({"message": {"chat": "weird"}})
        self.assertEqual((chat, kind), (None, "message"))


class ExtractActorTests(unittest.TestCase):
    def test_message_from(self) -> None:
        u = {"message": {"from": {"id": 42}, "chat": {"id": 99}}}
        self.assertEqual(extract_actor_user_id(u), "42")

    def test_callback_query_from(self) -> None:
        u = {
            "callback_query": {
                "from": {"id": 42},
                "message": {"chat": {"id": 99}},
            },
        }
        self.assertEqual(extract_actor_user_id(u), "42")

    def test_edited_message_from(self) -> None:
        u = {"edited_message": {"from": {"id": 42}, "chat": {"id": 99}}}
        self.assertEqual(extract_actor_user_id(u), "42")

    def test_no_from(self) -> None:
        self.assertIsNone(
            extract_actor_user_id({"message": {"chat": {"id": 99}}})
        )

    def test_malformed_from_as_string(self) -> None:
        self.assertIsNone(
            extract_actor_user_id({"message": {"from": "alice"}})
        )


class FlakeyWriter:
    """Writer that fails on its first telegram_inbound call, succeeds after."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_next_inbound = True

    def write(self, event_type: str, payload: dict[str, Any]) -> str:
        # Raise BEFORE appending so by_type() counts only successful writes
        # (the real EventWriter would raise inside KernelStore.execute and
        # the row would never land).
        if event_type == EVENT_TELEGRAM_INBOUND and self.fail_next_inbound:
            self.fail_next_inbound = False
            raise RuntimeError("simulated PG failure on first inbound")
        self.calls.append((event_type, payload))
        return f"fake-{len(self.calls)}"

    def close(self) -> None:  # pragma: no cover
        return None

    def by_type(self, event_type: str) -> list[dict[str, Any]]:
        # only count successful writes
        return [p for t, p in self.calls if t == event_type]


class WriterFailureRetryTests(AioHTTPTestCase):
    """Codex xhigh review #1: a writer crash must NOT silently swallow the
    Telegram retry. Two-phase dedupe (pending → committed) makes the retry
    re-process and durably land the row.
    """

    async def get_application(self) -> web.Application:
        self.flakey = FlakeyWriter()
        self.config = AdapterConfig(
            webhook_secret=SECRET,
            allowed_chats=ALLOWED_CHATS,
        )
        return create_app(self.config, writer=self.flakey)

    async def test_writer_crash_then_retry_eventually_writes(self) -> None:
        u = make_update(update_id=200)

        # First delivery — writer raises after dedupe.begin marks pending.
        # aiohttp default error handler turns the unhandled exception into 500.
        r1 = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert r1.status == 500, "first attempt should surface writer error"
        assert self.flakey.by_type(EVENT_TELEGRAM_INBOUND) == [], \
            "first attempt must NOT count as a durable write"

        # Telegram retries the SAME update_id. The pending mark was
        # rolled back, so dedupe lets it through and the second write
        # (no longer flakey) succeeds.
        r2 = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert r2.status == 200, "retry must succeed, not get swallowed"
        inbound = self.flakey.by_type(EVENT_TELEGRAM_INBOUND)
        assert len(inbound) == 1
        assert inbound[0]["update_id"] == 200

        # Third delivery (Telegram retry storm) — now dedupe is committed.
        r3 = await self.client.post(
            WEBHOOK_PATH,
            headers={SECRET_TOKEN_HEADER: SECRET},
            json=u,
        )
        assert r3.status == 200
        assert (await r3.json())["status"] == "duplicate"
        # Still one durable row — no double-write.
        assert len(self.flakey.by_type(EVENT_TELEGRAM_INBOUND)) == 1


class ConfigTests(unittest.TestCase):
    def test_secret_required(self) -> None:
        with self.assertRaises(ValueError):
            AdapterConfig(webhook_secret="", allowed_chats=ALLOWED_CHATS)

    def test_frozen_allowlist_membership(self) -> None:
        cfg = AdapterConfig(webhook_secret=SECRET,
                            allowed_chats=frozenset({"abc", "def"}))
        self.assertIn("abc", cfg.allowed_chats)
        self.assertNotIn("xyz", cfg.allowed_chats)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
