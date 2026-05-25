"""Unit tests for response_formatter. Pure — uses synthetic CheckResults."""

import unittest

from wannavegtour.availability_checker import CheckResult, CheckResultKind
from wannavegtour.query_parser import ParsedQuery, QueryIntent
from wannavegtour.response_formatter import format_response
from wannavegtour.wc_client import WCProduct


def make_product(**overrides):
    base = dict(
        id=255634,
        name="12/27【江南】烏鎮·西湖",
        slug="12-27",
        status="publish",
        permalink="https://wannavegtour.com/product/12-27/",
        regular_price="50900",
        sale_price="48900",
        stock_quantity=10,
        manage_stock=True,
        stock_status="instock",
        total_sales=0,
        date_modified="2026-05-25T10:00:00",
        departure_date="20261227",
        departure_month="12月",
        days="6",
        dep_airport=["桃園出發"],
        categories=["大陸港澳"],
    )
    base.update(overrides)
    return WCProduct(**base)


def make_query(text="12/27 江南", intent=QueryIntent.AVAILABILITY_CHECK, month=12, day=27, dest="江南"):
    return ParsedQuery(
        raw_text=text, intent=intent,
        month=month, day=day, destination_hint=dest, matched_year=2026,
    )


class TestFoundOne(unittest.TestCase):
    def test_basic_with_sale(self):
        r = CheckResult(kind=CheckResultKind.FOUND_ONE, query=make_query(), products=[make_product()])
        out = format_response(r)
        self.assertIn("🎯 12/27【江南】", out)
        self.assertIn("✅ 名額：10 位", out)
        self.assertIn("NT$48,900（原價 NT$50,900）", out)
        self.assertIn("6 天行程", out)
        self.assertIn("桃園出發", out)
        self.assertIn("https://wannavegtour.com/product/12-27/", out)
        self.assertIn("OP", out)  # hedge present

    def test_low_stock_warning(self):
        r = CheckResult(kind=CheckResultKind.FOUND_ONE, query=make_query(), products=[make_product(stock_quantity=2)])
        out = format_response(r)
        self.assertIn("⚠️", out)
        self.assertIn("只剩 2 位", out)

    def test_out_of_stock(self):
        r = CheckResult(kind=CheckResultKind.FOUND_ONE, query=make_query(), products=[make_product(stock_quantity=0)])
        out = format_response(r)
        self.assertIn("❌", out)
        self.assertIn("已售完", out)

    def test_unmanaged_stock(self):
        r = CheckResult(
            kind=CheckResultKind.FOUND_ONE, query=make_query(),
            products=[make_product(manage_stock=False, stock_quantity=None)],
        )
        out = format_response(r)
        self.assertIn("ℹ️", out)
        self.assertIn("未開啟庫存管理", out)

    def test_no_sale_no_paren(self):
        r = CheckResult(
            kind=CheckResultKind.FOUND_ONE, query=make_query(),
            products=[make_product(sale_price="50900")],   # sale == regular → no sale
        )
        out = format_response(r)
        self.assertNotIn("原價", out)


class TestFoundMany(unittest.TestCase):
    def test_lists_all_with_index(self):
        products = [
            make_product(id=1, name="7/9【韓國首爾】桃園出發", dep_airport=["桃園出發"], stock_quantity=12),
            make_product(id=2, name="7/9【韓國首爾】台中出發", dep_airport=["台中出發"], stock_quantity=8),
        ]
        q = make_query(text="7/9 韓國首爾", month=7, day=9, dest="韓國首爾")
        r = CheckResult(kind=CheckResultKind.FOUND_MANY, query=q, products=products)
        out = format_response(r)
        self.assertIn("找到 2 個", out)
        self.assertIn("1.", out)
        self.assertIn("2.", out)
        self.assertIn("剩 12 位", out)
        self.assertIn("剩 8 位", out)
        self.assertIn("回 1/2/3", out)


class TestNonProductOutcomes(unittest.TestCase):
    def test_found_none(self):
        r = CheckResult(
            kind=CheckResultKind.FOUND_NONE, query=make_query(),
            advisory=["查不到出發日 12/27 含『江南』的上架團。"],
        )
        out = format_response(r)
        self.assertTrue(out.startswith("🚫"))

    def test_need_destination(self):
        q = make_query(text="3/5", dest=None, month=3, day=5)
        r = CheckResult(
            kind=CheckResultKind.NEED_DESTINATION, query=q,
            advisory=["請補上目的地關鍵字"],
        )
        out = format_response(r)
        self.assertTrue(out.startswith("❓"))

    def test_refused_price_edit(self):
        r = CheckResult(
            kind=CheckResultKind.REFUSED_PRICE_EDIT,
            query=make_query(intent=QueryIntent.PRICE_EDIT_HINT),
            advisory=["這看起來是改價"],
        )
        out = format_response(r)
        self.assertTrue(out.startswith("🙅"))

    def test_unclear(self):
        r = CheckResult(
            kind=CheckResultKind.UNCLEAR, query=make_query(intent=QueryIntent.UNCLEAR),
            advisory=["訊息不明確"],
        )
        out = format_response(r)
        self.assertTrue(out.startswith("🤔"))

    def test_error_includes_debug(self):
        r = CheckResult(
            kind=CheckResultKind.ERROR, query=make_query(),
            advisory=["WooCommerce API 出錯"],
            error_message="connection refused",
        )
        out = format_response(r)
        self.assertTrue(out.startswith("💥"))
        self.assertIn("[debug]", out)
        self.assertIn("connection refused", out)


if __name__ == "__main__":
    unittest.main()
