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


def _mk_config(target_groups=None, invocation_prefixes=None):
    return LineConfig(
        channel_id="cid", channel_secret="cs", channel_access_token="cat",
        bot_basic_id="@bot", bot_user_id="Uself",
        target_groups=target_groups or [],
        invocation_prefixes=tuple(invocation_prefixes) if invocation_prefixes is not None
                            else ("小弟", "@小弟", "/小弟"),
    )


def _mk_event(text="3/5 江南還收嗎", *, event_type="message", message_type="text",
              source_type="group", group_id="Cgroup", user_id="Uuser",
              reply_token="rt", mention_is_self=False,
              mention_self_index=None, mention_self_length=None):
    return LineEvent(
        event_type=event_type, message_type=message_type,
        text=text, source_type=source_type,
        group_id=group_id, user_id=user_id,
        reply_token=reply_token, timestamp_ms=1,
        message_id="m1", mention_is_self=mention_is_self,
        mention_self_index=mention_self_index,
        mention_self_length=mention_self_length,
        raw={},
    )


def _mk_router(target_groups=None, invocation_prefixes=None):
    availability = MagicMock()
    historical = MagicMock()
    config = _mk_config(target_groups, invocation_prefixes)
    return LineRouter(config, availability, historical), availability, historical


class TestPassiveListeningMode(unittest.TestCase):
    """Pattern B: bot stays silent on every message unless @mentioned.
    Intent is still parsed + recorded in audit, but no LINE reply is sent."""

    def test_availability_query_without_mention_is_silent(self):
        router, avail, _ = _mk_router()
        result = router.dispatch(_mk_event("3/5 江南還收嗎"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertEqual(result.intent, QueryIntent.AVAILABILITY_CHECK.value)
        self.assertIn("passive listening", result.skip_reason or "")
        self.assertTrue(result.audit_extras.get("would_have_replied"))
        avail.check.assert_not_called()   # worker not invoked

    def test_historical_query_without_mention_is_silent(self):
        router, _, hist = _mk_router()
        result = router.dispatch(_mk_event("不丹有沒有成團"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertEqual(result.intent, QueryIntent.HISTORICAL_LOOKUP.value)
        hist.lookup.assert_not_called()

    def test_price_edit_without_mention_is_silent_no_telegram(self):
        """Even sensitive PRICE_EDIT_HINT does NOT trigger Telegram noise
        in passive mode — user is in the loop, no need to alert."""
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("5/6 改80000"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertEqual(result.intent, QueryIntent.PRICE_EDIT_HINT.value)

    def test_chitchat_without_mention_silent(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("中午吃什麼"))
        self.assertEqual(result.action, DispatchAction.SILENT)


class TestMentionDispatch(unittest.TestCase):
    """When @mentioned, bot processes intent + replies (text passed through
    _strip_bot_mention first so the parser doesn't see the @ prefix)."""

    def test_availability_routes_to_checker_when_mentioned(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
            advisory=["查不到"],
        )
        # "@bot 3/5 江南還收嗎" → mention at index 0 length 4
        result = router.dispatch(_mk_event(
            "@bot 3/5 江南還收嗎", mention_is_self=True,
            mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.worker, "availability_checker")
        self.assertIsNotNone(result.reply_text)
        avail.check.assert_called_once()
        # Cleaned text should have @bot stripped before parser sees it.
        self.assertEqual(result.audit_extras["cleaned_text"], "3/5 江南還收嗎")

    def test_historical_routes_to_lookup_when_mentioned(self):
        router, _, hist = _mk_router()
        hist.lookup.return_value = HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.HISTORICAL_LOOKUP,
                              month=None, day=None, destination_hint="不丹", matched_year=None),
            advisory=["查不到"],
        )
        result = router.dispatch(_mk_event(
            "@bot 不丹有沒有成團", mention_is_self=True,
            mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.worker, "historical_lookup")

    def test_price_edit_replies_with_refusal_when_mentioned(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event(
            "@bot 5/6 改80000", mention_is_self=True,
            mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.intent, QueryIntent.PRICE_EDIT_HINT.value)
        self.assertIn("自動執行尚未上線", result.reply_text or "")
        # Critical: NOT ALERT_TELEGRAM under passive-listening discipline.
        self.assertNotEqual(result.action, DispatchAction.ALERT_TELEGRAM)

    def test_unclear_acks_when_mentioned(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event(
            "@bot 你好啊", mention_is_self=True,
            mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.reply_text, UNCLEAR_ACK_TEXT)

    def test_mention_with_no_indices_falls_back_safely(self):
        """If LINE didn't send mention.index/length but did flag isSelf,
        we should still process — just without precise @ stripping."""
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            "3/5 江南", mention_is_self=True,
            mention_self_index=None, mention_self_length=None,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)
        avail.check.assert_called_once()


class TestInvocationByPrefix(unittest.TestCase):
    """Text-prefix invocation path — works on every LINE client including
    desktop where Bot Mention autocomplete is not supported.

    Prefixes default to (小弟, @小弟, /小弟). Strict startswith match
    after text.strip(). Mention path remains primary when present."""

    def test_prefix_triggers_availability_check(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event("小弟 12/27 江南還收嗎"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.worker, "availability_checker")
        self.assertEqual(result.audit_extras["invocation"], "prefix:小弟")
        self.assertEqual(result.audit_extras["cleaned_text"], "12/27 江南還收嗎")

    def test_at_prefix_alias(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="峴港", matched_year=2026),
        )
        result = router.dispatch(_mk_event("@小弟 3/5 峴港"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.audit_extras["invocation"], "prefix:@小弟")
        self.assertEqual(result.audit_extras["cleaned_text"], "3/5 峴港")

    def test_slash_prefix_alias(self):
        router, _, hist = _mk_router()
        hist.lookup.return_value = HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.HISTORICAL_LOOKUP,
                              month=None, day=None, destination_hint="不丹", matched_year=None),
        )
        result = router.dispatch(_mk_event("/小弟 不丹有沒有成團"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.audit_extras["invocation"], "prefix:/小弟")

    def test_prefix_with_leading_whitespace_still_triggers(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event("  小弟 12/27 江南"))
        self.assertEqual(result.action, DispatchAction.REPLY)

    def test_no_space_after_prefix_still_triggers(self):
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event("小弟12/27 江南"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        # cleaned text should drop the "小弟" prefix
        self.assertEqual(result.audit_extras["cleaned_text"], "12/27 江南")

    def test_prefix_mid_sentence_does_NOT_trigger(self):
        """'我小弟最近想旅遊' must NOT trigger — '小弟' is not at start."""
        router, avail, _ = _mk_router()
        result = router.dispatch(_mk_event("我小弟最近想旅遊"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        self.assertIn("not invoked", result.skip_reason or "")
        avail.check.assert_not_called()

    def test_mention_wins_over_prefix(self):
        """If BOTH mention.isSelf and prefix are present, mention path is used
        (richer signal with exact LINE-provided offsets)."""
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            "@小弟 12/27 江南", mention_is_self=True,
            mention_self_index=0, mention_self_length=3,
        ))
        self.assertEqual(result.audit_extras["invocation"], "mention")

    def test_configurable_prefixes_override_default(self):
        router, avail, _ = _mk_router(invocation_prefixes=["阿玩", "bot"])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        # "小弟" no longer triggers
        result = router.dispatch(_mk_event("小弟 12/27 江南"))
        self.assertEqual(result.action, DispatchAction.SILENT)
        # "阿玩" does
        result = router.dispatch(_mk_event("阿玩 12/27 江南"))
        self.assertEqual(result.action, DispatchAction.REPLY)


class TestHelpCommand(unittest.TestCase):
    """`小弟 ?` (and variants) return a plain-Chinese functionality summary."""

    def test_question_mark_alone_triggers_help(self):
        router, avail, hist = _mk_router()
        result = router.dispatch(_mk_event("小弟 ?"))
        self.assertEqual(result.action, DispatchAction.REPLY)
        self.assertEqual(result.intent, "help_request")
        self.assertIn("查名額", result.reply_text or "")
        self.assertIn("問歷史團", result.reply_text or "")
        self.assertIn("賣最好排行", result.reply_text or "")
        avail.check.assert_not_called()
        hist.lookup.assert_not_called()

    def test_fullwidth_question_mark_triggers_help(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("小弟 ？"))
        self.assertEqual(result.intent, "help_request")

    def test_english_help_triggers_help(self):
        router, _, _ = _mk_router()
        for trigger in ("小弟 help", "小弟 Help", "小弟 HELP"):
            result = router.dispatch(_mk_event(trigger))
            self.assertEqual(result.intent, "help_request", trigger)

    def test_chinese_help_words_trigger(self):
        router, _, _ = _mk_router()
        for trigger in ("小弟 幫助", "小弟 說明", "小弟 指令", "小弟 功能", "小弟 怎麼用"):
            result = router.dispatch(_mk_event(trigger))
            self.assertEqual(result.intent, "help_request", trigger)

    def test_help_via_at_prefix(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("@小弟 ?"))
        self.assertEqual(result.intent, "help_request")

    def test_help_via_mobile_mention(self):
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event(
            "@阿玩旅遊OP專用機器人 ?", mention_is_self=True,
            mention_self_index=0, mention_self_length=12,
        ))
        self.assertEqual(result.intent, "help_request")

    def test_question_mark_inside_real_query_does_NOT_trigger_help(self):
        """『小弟 12/27 江南還收嗎？』has '?' but isn't a help request — it's
        a real availability question that just happens to end with ?."""
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=12, day=27, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event("小弟 12/27 江南還收嗎？"))
        self.assertEqual(result.intent, QueryIntent.AVAILABILITY_CHECK.value)
        self.assertNotEqual(result.intent, "help_request")
        avail.check.assert_called_once()

    def test_question_mark_without_invocation_stays_silent(self):
        """Bare '?' (no 小弟 / no @) must NOT trigger help — bot is passive
        unless explicitly invoked."""
        router, _, _ = _mk_router()
        result = router.dispatch(_mk_event("?"))
        self.assertEqual(result.action, DispatchAction.SILENT)

    def test_help_only_invocation_with_extra_text_is_NOT_help(self):
        """『小弟 ? 還有別的嗎』isn't a help request — the trailing text
        means the user actually asked something; fall through to parser.

        The exact downstream intent is the parser's call (it may pick up
        '還有' as an availability keyword and route to NEED_DATE, etc.);
        what matters here is that the help gate did NOT fire."""
        router, avail, _ = _mk_router()
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.NEED_DATE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=None, day=None,
                              destination_hint="還有別的嗎", matched_year=None),
            advisory=["請補出發日"],
        )
        result = router.dispatch(_mk_event("小弟 ? 還有別的嗎"))
        self.assertNotEqual(result.intent, "help_request")


class TestStripBotMention(unittest.TestCase):
    """Cover the _strip_bot_mention helper directly — covers CJK + edge cases."""

    def test_strip_basic_ascii_mention(self):
        from wannavegtour.line_router import _strip_bot_mention
        # "@hermes 3/5 江南" with mention at 0 length 7
        self.assertEqual(_strip_bot_mention("@hermes 3/5 江南", 0, 7), "3/5 江南")

    def test_strip_cjk_display_name(self):
        from wannavegtour.line_router import _strip_bot_mention
        # "@小幫手 12/27" — @ + 3 CJK chars = 4 chars
        self.assertEqual(_strip_bot_mention("@小幫手 12/27", 0, 4), "12/27")

    def test_strip_mention_mid_text(self):
        from wannavegtour.line_router import _strip_bot_mention
        # Mention not at start: "請問 @bot 多少錢"
        # @bot at index 3 length 4
        out = _strip_bot_mention("請問 @bot 多少錢", 3, 4)
        self.assertEqual(out, "請問  多少錢")

    def test_missing_indices_returns_stripped_text(self):
        from wannavegtour.line_router import _strip_bot_mention
        self.assertEqual(_strip_bot_mention("  hello  ", None, None), "hello")

    def test_out_of_bounds_indices_falls_back(self):
        from wannavegtour.line_router import _strip_bot_mention
        # index+length exceeds text length — fall back to original (trimmed).
        self.assertEqual(_strip_bot_mention("hi", 0, 999), "hi")

    def test_empty_text(self):
        from wannavegtour.line_router import _strip_bot_mention
        self.assertEqual(_strip_bot_mention("", 0, 5), "")


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
        """Whitelist allows the group through, then passive mode still applies —
        bot only replies when @mentioned."""
        router, avail, _ = _mk_router(target_groups=["CallowedGroup"])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            text="@bot 3/5 江南還收嗎", group_id="CallowedGroup",
            mention_is_self=True, mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)

    def test_empty_whitelist_allows_any_group(self):
        router, avail, _ = _mk_router(target_groups=[])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            text="@bot 3/5 江南還收嗎", group_id="Cany",
            mention_is_self=True, mention_self_index=0, mention_self_length=4,
        ))
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
        """No target_groups set → bot accepts all sources. Passive mode still
        applies, so @mention is required to elicit a reply."""
        router, avail, _ = _mk_router(target_groups=[])
        avail.check.return_value = CheckResult(
            kind=CheckResultKind.FOUND_NONE,
            query=ParsedQuery(raw_text="x", intent=QueryIntent.AVAILABILITY_CHECK,
                              month=3, day=5, destination_hint="江南", matched_year=2026),
        )
        result = router.dispatch(_mk_event(
            text="@bot 3/5 江南還收嗎", source_type="user", group_id=None, user_id="Uany",
            mention_is_self=True, mention_self_index=0, mention_self_length=4,
        ))
        self.assertEqual(result.action, DispatchAction.REPLY)


if __name__ == "__main__":
    unittest.main()
