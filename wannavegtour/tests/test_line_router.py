"""Unit tests for LineRouter dispatch decisions.

Uses MagicMock for AvailabilityChecker / HistoricalLookup — pure routing logic
under test, no real workers.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from wannavegtour.availability_checker import CheckResult, CheckResultKind
from wannavegtour.config import LineConfig
from wannavegtour.historical_lookup import HistoricalLookupKind, HistoricalResult
from wannavegtour.line_client import LineEvent
from wannavegtour.line_router import DispatchAction, LineRouter, PRICE_EDIT_REFUSAL_TEXT, UNCLEAR_ACK_TEXT
from wannavegtour.query_parser import ParsedQuery, QueryIntent


def _mk_config(target_groups=None):
    return LineConfig(
        channel_id="cid", channel_secret="cs", channel_access_token="cat",
        bot_basic_id="@bot", bot_user_id="Uself",
        target_groups=target_groups or [],
    )


def _mk_event(text="3/5 江南還收嗎", *, event_type="message", message_type="text",
              source_type="group", group_id="Cgroup", user_id="Uuser",
              reply_token="rt", mention_is_self=False):
    return LineEvent(
        event_type=event_type, message_type=message_type,
        text=text, source_type=source_type,
        group_id=group_id, user_id=user_id,
        reply_token=reply_token, timestamp_ms=1,
        message_id="m1", mention_is_self=mention_is_self,
        raw={},
    )


def _mk_router(target_groups=None):
    availability = MagicMock()
    historical = MagicMock()
    return LineRouter(_mk_config(target_groups), availability, historical), availability, historical


class TestRouterCoreDispatch(unittest.TestCase):

    def test_availability_routes_to_checker(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
            advisory=["查不到"],
        )
        result = router.dispatch(_mk_event("3/5 江南還收嗎"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.worker, "availability_checker")
        self.assertIsNotNone(result.reply_text)
        avail.check.assert_called_once()

    def test_historical_routes_to_lookup(self):
        router, _, hist = _mk_router()
        hist.lookup.return_value = HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.HISTORICAL_LOOKUP,
                              month=None, day=None, destination_hint="不丹", matched_year=None),
            advisory=["查不到"],
        )
        result = router.dispatch(_mk_event("不丹有沒有成團"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.worker, "historical_lookup")
        hist.lookup.assert_called_once()

    def test_price_edit_alerts_telegram_does_not_reply_in_line(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("5/6 改80000"))
        self.assertEqual(result.action, DispatchAction.ALERT_TELEGRAM)
        # The reply_text is set so the listener could route it elsewhere, but action says alert.
        self.assertEqual(result.intent, QueryIntent.PRICE_EDIT_HINT.value)

    def test_unclear_goes_silent_when_not_mentioned(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("你好啊"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertEqual(result.intent, QueryIntent.UNCLEAR.value)

    def test_unclear_acks_when_mentioned(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("@hermes 你好啊", mention_is_self=True))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.reply_text, UNCLEAR_ACK_TEXT)


class TestRouterFilters(unittest.TestCase):

    def test_non_message_event_silent(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event(event_type="join", message_type=None, text=None))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertIn("non-text", result.skip_reason or "")

    def test_image_message_silent(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event(message_type="image", text=None))
        self.assertEqual(result.action, DispatchAction.SILENT)

    def test_group_whitelist_blocks_other_groups(self):
        router, avail, _ = _mk_router(target_groups=["CallowedGroup"])
        result = router.dispatch(_mk_event(text="3/5 江南", group_id="Cother"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertIn("whitelist", result.skip_reason or "")
        # avail.check should NOT have been called
        avail.check.assert_not_called()

    def test_group_whitelist_allows_listed_group(self):
        router, avail, _ = _mk_router(target_groups=["CallowedGroup"])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(text="3/5 江南還收嗎", group_id="CallowedGroup"))
        self.assertEqual(result.action, DispatchAction.REPLY)

    def test_empty_whitelist_allows_any_group(self):
        router, avail, _ = _mk_router(target_groups=[])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(text="3/5 江南還收嗎", group_id="Cany"))
        self.assertEqual(result.action, DispatchAction.REPLY)


class TestCodexRegression_WhitelistBypass(unittest.TestCase):
    """Codex review 2026-05-25 P1: when target_groups is set, non-group sources
    (direct messages, multi-person rooms) must NOT bypass the whitelist by virtue
    of having no groupId. They are rejected outright."""

    def test_dm_rejected_when_whitelist_active(self):
        router, avail, _ = _mk_router(target_groups=["CallowedGroup"])
        result = router.dispatch(_mk_event(
            text="3/5 江南還收嗎", source_type="user", group_id=None, user_id="Uattacker",
        ))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertIn("non-group", result.skip_reason or "")
        avail.check.assert_not_called()

    def test_room_rejected_when_whitelist_active(self):
        router, avail, _ = _mk_router(target_groups=["CallowedGroup"])
        result = router.dispatch(_mk_event(
            text="3/5 江南", source_type="room", group_id=None, user_id="Usomeone",
        ))
        self.assertEqual(result.action, DispatchAction.SILENT)
        avail.check.assert_not_called()

    def test_dm_allowed_when_no_whitelist(self):
        """No target_groups set → bot accepts all sources (current default)."""
        router, avail, _ = _mk_router(target_groups=[])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            text="3/5 江南還收嗎", source_type="user", group_id=None, user_id="Uany",
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)


if __name__ == "__main__":
    unittest.main()
