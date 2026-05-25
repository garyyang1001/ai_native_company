"""Unit tests for query_parser. Pure — no network."""

import datetime as dt
import unittest

from wannavegtour.query_parser import (
    QueryIntent,
    _parse_chinese_number,
    _normalize,
    _infer_year,
    parse_query,
)


class TestChineseNumber(unittest.TestCase):
    def test_single_digit(self):
        for ch, n in [("一", 1), ("二", 2), ("三", 3), ("九", 9), ("十", 10)]:
            self.assertEqual(_parse_chinese_number(ch), n)

    def test_ten_x(self):
        self.assertEqual(_parse_chinese_number("十一"), 11)
        self.assertEqual(_parse_chinese_number("十二"), 12)
        self.assertEqual(_parse_chinese_number("十九"), 19)

    def test_x_ten(self):
        self.assertEqual(_parse_chinese_number("二十"), 20)
        self.assertEqual(_parse_chinese_number("三十"), 30)

    def test_x_ten_y(self):
        self.assertEqual(_parse_chinese_number("二十五"), 25)
        self.assertEqual(_parse_chinese_number("三十一"), 31)

    def test_variants(self):
        self.assertEqual(_parse_chinese_number("壹"), 1)
        self.assertEqual(_parse_chinese_number("兩"), 2)
        self.assertEqual(_parse_chinese_number("〇"), 0)
        self.assertEqual(_parse_chinese_number("拾"), 10)

    def test_invalid(self):
        self.assertIsNone(_parse_chinese_number(""))
        self.assertIsNone(_parse_chinese_number("abc"))
        self.assertIsNone(_parse_chinese_number("百"))


class TestNormalize(unittest.TestCase):
    def test_fullwidth_digits(self):
        self.assertEqual(_normalize("１２/２７"), "12/27")
        self.assertEqual(_normalize("３月５日"), "3月5日")

    def test_fullwidth_slash(self):
        self.assertEqual(_normalize("3／5"), "3/5")
        self.assertEqual(_normalize("3．5"), "3.5")

    def test_passthrough_chinese(self):
        self.assertEqual(_normalize("江南"), "江南")
        self.assertEqual(_normalize("還有"), "還有")


class TestInferYear(unittest.TestCase):
    def test_future_date_this_year(self):
        today = dt.date(2026, 5, 25)
        # 12/27 is future this year → 2026
        self.assertEqual(_infer_year(12, 27, today), 2026)

    def test_past_date_next_year(self):
        today = dt.date(2026, 5, 25)
        # 3/5 is past this year → 2027
        self.assertEqual(_infer_year(3, 5, today), 2027)

    def test_today_keeps_this_year(self):
        today = dt.date(2026, 5, 25)
        self.assertEqual(_infer_year(5, 25, today), 2026)


class TestParseDate(unittest.TestCase):
    def test_slash(self):
        p = parse_query("3/5 江南")
        self.assertEqual((p.month, p.day), (3, 5))

    def test_dash(self):
        p = parse_query("3-5 江南")
        self.assertEqual((p.month, p.day), (3, 5))

    def test_dot(self):
        p = parse_query("3.5 江南")
        self.assertEqual((p.month, p.day), (3, 5))

    def test_yue_ri(self):
        p = parse_query("3月5日 江南")
        self.assertEqual((p.month, p.day), (3, 5))

    def test_chinese_yue_ri(self):
        p = parse_query("十二月二十七日 江南")
        self.assertEqual((p.month, p.day), (12, 27))

    def test_fullwidth(self):
        p = parse_query("１２/２７ 江南")
        self.assertEqual((p.month, p.day), (12, 27))

    def test_hao_suffix(self):
        p = parse_query("3/5號 江南")
        self.assertEqual((p.month, p.day), (3, 5))


class TestIntent(unittest.TestCase):
    def test_availability_kw(self):
        cases = [
            "3/5 江南還有位嗎",
            "3/5 江南剩多少？",
            "12/27 那團怎麼樣",
            "12/27 名額",
        ]
        for c in cases:
            self.assertEqual(parse_query(c).intent, QueryIntent.AVAILABILITY_CHECK, c)

    def test_price_edit_refused(self):
        cases = [
            "5/6 改80000",
            "5/6 改8萬",
            "5/6 調成 28,900",
            "5/6 價格改成 30000",
        ]
        for c in cases:
            self.assertEqual(parse_query(c).intent, QueryIntent.PRICE_EDIT_HINT, c)

    def test_unclear(self):
        cases = [
            "",
            "你好啊",
            "12/27",                # date alone — no destination, no avail kw
        ]
        for c in cases:
            self.assertEqual(parse_query(c).intent, QueryIntent.UNCLEAR, c)

    def test_date_plus_destination_implies_availability(self):
        p = parse_query("12/27 江南")
        self.assertEqual(p.intent, QueryIntent.AVAILABILITY_CHECK)


class TestDestinationCleanup(unittest.TestCase):
    def test_strips_strip_tokens(self):
        p = parse_query("峴港3-15還有位嗎")
        self.assertEqual(p.destination_hint, "峴港")

    def test_strips_combined_phrase(self):
        # "還剩多少" should fully strip, no orphan "還"
        p = parse_query("3/5 那團怎麼樣？還剩多少？")
        self.assertIsNone(p.destination_hint)

    def test_preserves_multi_destination_tokens(self):
        # User mentions both destination and 出發地 — both should pass through.
        p = parse_query("韓國首爾 9/15 高雄那團還收嗎")
        self.assertIn("韓國首爾", p.destination_hint)
        self.assertIn("高雄", p.destination_hint)


class TestExtras(unittest.TestCase):
    def test_extras_carry_date_substring(self):
        p = parse_query("12/27 江南")
        self.assertIn("normalized", p.extras)
        self.assertEqual(p.extras["date_substring"], "12/27")


class TestDateFields(unittest.TestCase):
    def test_mmdd(self):
        p = parse_query("3/5 江南")
        self.assertEqual(p.departure_date_mmdd, "0305")

    def test_full(self):
        today = dt.date(2026, 5, 25)
        p = parse_query("12/27 江南", today=today)
        self.assertEqual(p.departure_date_full, "20261227")


class TestHistoricalIntent(unittest.TestCase):
    def test_lifecycle_keyword(self):
        for q in ["7/22 暑假成團多少人？", "不丹有沒有成團", "過年那團最後額滿了嗎？"]:
            self.assertEqual(parse_query(q).intent, QueryIntent.HISTORICAL_LOOKUP, q)

    def test_aggregate_keyword(self):
        for q in ["今年賣最好的是哪些團？", "去年賣最多的團", "Top 5"]:
            self.assertEqual(parse_query(q).intent, QueryIntent.HISTORICAL_LOOKUP, q)

    def test_past_tense_keyword(self):
        for q in ["上次峴港那團", "之前江南那團"]:
            self.assertEqual(parse_query(q).intent, QueryIntent.HISTORICAL_LOOKUP, q)

    def test_lifecycle_hint_recorded(self):
        p = parse_query("7/22 暑假成團多少人？")
        self.assertEqual(p.extras["lifecycle_hint"], "成團")

    def test_year_qualifier_recorded(self):
        p = parse_query("今年賣最好的")
        self.assertEqual(p.extras["year_qualifier"], "今年")
        self.assertTrue(p.extras["is_aggregate"])

    def test_destination_hint_cleaned_for_historical(self):
        p = parse_query("7/22 暑假成團多少人？")
        self.assertEqual(p.destination_hint, "暑假")  # lifecycle keyword stripped
        p = parse_query("不丹有沒有成團")
        self.assertEqual(p.destination_hint, "不丹")
        p = parse_query("過年那團最後額滿了嗎？")
        self.assertEqual(p.destination_hint, "過年")

    def test_aggregate_destination_hint_none(self):
        p = parse_query("今年賣最好的是哪些團？")
        self.assertIsNone(p.destination_hint)

    def test_does_not_strip_cheng_du(self):
        # Verify "成" alone is NOT stripped — would break 成都 / 達成 if it were.
        # We only strip "成團" multi-char. Plain "成" stays.
        from wannavegtour.query_parser import _STRIP_TOKENS
        self.assertNotIn("成", _STRIP_TOKENS)


class TestHistoricalDoesNotBreakType1(unittest.TestCase):
    """Make sure adding historical intent didn't regress Type 1 parsing."""

    def test_type1_unchanged(self):
        cases = [
            ("12/27 江南還收嗎", QueryIntent.AVAILABILITY_CHECK, "江南"),
            ("峴港3-15還有位嗎", QueryIntent.AVAILABILITY_CHECK, "峴港"),
            ("不丹 9/9 還有位嗎", QueryIntent.AVAILABILITY_CHECK, "不丹"),
        ]
        for text, intent, dest in cases:
            p = parse_query(text)
            self.assertEqual(p.intent, intent, text)
            self.assertEqual(p.destination_hint, dest, text)


class TestCodexRegressionRouting(unittest.TestCase):
    """Regression tests for codex review 2026-05-25 P1 finding:
    person-count / 報名 wording in CURRENT availability context must route to
    AVAILABILITY_CHECK, not HISTORICAL_LOOKUP. Historical routing requires a
    lifecycle marker (成團/額滿/...), past-tense word, or aggregate keyword."""

    def test_duo_shao_ren_with_availability_kw_is_availability(self):
        # "還剩多少人" — current question, NOT historical
        for q in [
            "3/5 江南還剩多少人？",
            "12/27 江南剩多少人",
            "不丹 9/9 還有多少人",
        ]:
            self.assertEqual(parse_query(q).intent, QueryIntent.AVAILABILITY_CHECK, q)

    def test_bao_ming_in_availability_context_is_availability(self):
        # "還能報名嗎" — current question, NOT historical
        for q in [
            "3/5 江南還能報名嗎",
            "峴港3/15還能報嗎",
        ]:
            self.assertEqual(parse_query(q).intent, QueryIntent.AVAILABILITY_CHECK, q)

    def test_person_count_with_lifecycle_marker_is_historical(self):
        # "成團多少人" — lifecycle marker still triggers historical
        self.assertEqual(parse_query("7/22 暑假成團多少人？").intent, QueryIntent.HISTORICAL_LOOKUP)
        self.assertEqual(parse_query("不丹 額滿多少人").intent, QueryIntent.HISTORICAL_LOOKUP)

    def test_person_count_with_past_tense_is_historical(self):
        # "上次" past-tense kicks historical even without lifecycle marker
        self.assertEqual(parse_query("上次峴港那團多少人").intent, QueryIntent.HISTORICAL_LOOKUP)


class TestAggregateColloquialVariants(unittest.TestCase):
    """Real OP query that failed in production: '我們最近賣的最好的是那些？ 列10團來'.
    Spoken Chinese inserts 的 / 得 between 賣 and 最好/最多. Plus '最近' as
    year qualifier wasn't covered before."""

    def test_garys_exact_failed_query(self):
        p = parse_query("我們最近賣的最好的是那些？ 列10團來")
        self.assertEqual(p.intent, QueryIntent.HISTORICAL_LOOKUP)
        self.assertTrue(p.extras["is_aggregate"])
        self.assertEqual(p.extras["year_qualifier"], "最近")

    def test_de_variants_match_aggregate(self):
        for q in ("賣的最好", "賣的最多", "賣得最好", "賣得最多"):
            p = parse_query(q)
            self.assertEqual(p.intent, QueryIntent.HISTORICAL_LOOKUP, q)
            self.assertTrue(p.extras["is_aggregate"], q)

    def test_zui_jin_year_qualifier(self):
        p = parse_query("最近賣最好的")
        self.assertEqual(p.extras["year_qualifier"], "最近")

    def test_original_phrasing_still_works(self):
        """Regression: '今年賣最好的團' must still work after adding variants."""
        p = parse_query("今年賣最好的團")
        self.assertEqual(p.intent, QueryIntent.HISTORICAL_LOOKUP)
        self.assertTrue(p.extras["is_aggregate"])
        self.assertEqual(p.extras["year_qualifier"], "今年")


if __name__ == "__main__":
    unittest.main()
