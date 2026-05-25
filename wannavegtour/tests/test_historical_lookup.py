"""Tests for HistoricalLookup.

Unit tests use a fake WCClient (no network).
Live tests run against real wannavegtour.com when HERMES_WANNAVEG_LIVE=1.
"""

from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest.mock import MagicMock

from wannavegtour import (
    HistoricalLookup,
    HistoricalLookupKind,
    WCClient,
    format_historical,
    load_config,
    parse_query,
)
from wannavegtour.wc_client import WCProduct


LIVE = os.environ.get("HERMES_WANNAVEG_LIVE") == "1"


def _mkproduct(
    *, id=1, name="dummy", status="publish", total_sales=0,
    stock_quantity=10, manage_stock=True, departure_date=None,
    date_modified="2026-05-01T00:00:00", regular_price="50000", sale_price="",
):
    return WCProduct(
        id=id, name=name, slug=f"p-{id}", status=status,
        permalink=f"https://wannavegtour.com/product/p-{id}/",
        regular_price=regular_price, sale_price=sale_price,
        stock_quantity=stock_quantity, manage_stock=manage_stock,
        stock_status="instock",
        total_sales=total_sales, date_modified=date_modified,
        departure_date=departure_date,
        departure_month=None, days=None, dep_airport=[], categories=[],
    )


class TestHistoricalUnit(unittest.TestCase):
    """Unit-level: HistoricalLookup with a mock WCClient."""

    def test_aggregate_sort_by_total_sales(self):
        client = MagicMock(spec=WCClient)
        client.search_products.return_value = [
            _mkproduct(id=1, name="A", total_sales=50, date_modified="2026-01-01T00:00:00"),
            _mkproduct(id=2, name="B", total_sales=100, date_modified="2026-02-01T00:00:00"),
            _mkproduct(id=3, name="C", total_sales=20, date_modified="2026-03-01T00:00:00"),
        ]
        h = HistoricalLookup(client)
        result = h.lookup(parse_query("今年賣最好的"))
        self.assertEqual(result.kind, HistoricalLookupKind.AGGREGATE_TOP)
        # Top should be B (100), then A (50), then C (20).
        self.assertEqual([p.id for p in result.products], [2, 1, 3])

    def test_aggregate_year_filter_uses_date_modified(self):
        client = MagicMock(spec=WCClient)
        # Year qualifier is "今年" → current year; pretend today is 2026.
        client.search_products.return_value = [
            _mkproduct(id=1, total_sales=99, date_modified="2025-12-31T00:00:00"),
            _mkproduct(id=2, total_sales=10, date_modified="2026-01-15T00:00:00"),
        ]
        h = HistoricalLookup(client)
        # parse_query with today=2026 to make "今年" mean 2026
        q = parse_query("今年賣最好的", today=dt.date(2026, 5, 1))
        # Override year resolution via patching today — use the public path:
        result = h.lookup(q)
        # Only id=2 (2026) survives filter
        self.assertEqual(result.kind, HistoricalLookupKind.AGGREGATE_TOP)
        self.assertEqual([p.id for p in result.products], [2])

    def test_aggregate_zero_sales_filtered_out(self):
        client = MagicMock(spec=WCClient)
        client.search_products.return_value = [
            _mkproduct(id=1, total_sales=0),
            _mkproduct(id=2, total_sales=5),
        ]
        h = HistoricalLookup(client)
        result = h.lookup(parse_query("Top 5"))
        self.assertEqual(result.kind, HistoricalLookupKind.AGGREGATE_TOP)
        self.assertEqual([p.id for p in result.products], [2])

    def test_specific_lifecycle_filter(self):
        client = MagicMock(spec=WCClient)
        # 1 with 【成團】, 1 with 【額滿】, 1 plain
        client.search_products.return_value = [
            _mkproduct(id=1, name="【成團】不丹A", status="private", total_sales=20, departure_date="20250722"),
            _mkproduct(id=2, name="【額滿】不丹B", status="private", total_sales=30, departure_date="20250722"),
            _mkproduct(id=3, name="不丹C 草稿", status="private", total_sales=0, departure_date="20250722"),
        ]
        h = HistoricalLookup(client)
        # Query mentions 成團 → should filter to id=1
        result = h.lookup(parse_query("不丹有沒有成團"))
        self.assertEqual(result.kind, HistoricalLookupKind.LIFECYCLE_FOUND_ONE)
        self.assertEqual(result.products[0].id, 1)

    def test_specific_need_query_detail_when_empty(self):
        client = MagicMock(spec=WCClient)
        h = HistoricalLookup(client)
        # "有沒有成團" alone — no destination, no date
        result = h.lookup(parse_query("有沒有成團"))
        self.assertEqual(result.kind, HistoricalLookupKind.NEED_QUERY_DETAIL)

    def test_wrong_intent_returns_unclear(self):
        client = MagicMock(spec=WCClient)
        h = HistoricalLookup(client)
        # Pass a Type 1 query — should refuse via UNCLEAR.
        result = h.lookup(parse_query("12/27 江南還收嗎"))
        self.assertEqual(result.kind, HistoricalLookupKind.UNCLEAR)


class TestHistoricalFormatter(unittest.TestCase):
    def test_aggregate_top_format(self):
        from wannavegtour.historical_lookup import HistoricalResult
        q = parse_query("今年賣最好的")
        products = [
            _mkproduct(id=1, name="【額滿】青森", total_sales=36, date_modified="2026-03-20T10:00:00"),
            _mkproduct(id=2, name="【成團】京都", total_sales=32, date_modified="2026-02-15T10:00:00"),
        ]
        r = HistoricalResult(
            kind=HistoricalLookupKind.AGGREGATE_TOP, query=q, products=products,
            extras={"year_qualifier": "今年", "scope_note": "test scope"},
        )
        out = format_historical(r)
        self.assertIn("🏆 今年", out)
        self.assertIn("1. 【額滿】青森", out)
        self.assertIn("36 人", out)
        self.assertIn("32 人", out)
        self.assertIn("test scope", out)

    def test_lifecycle_one_chengtuan(self):
        from wannavegtour.historical_lookup import HistoricalResult
        q = parse_query("不丹有沒有成團")
        r = HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_ONE, query=q,
            products=[_mkproduct(id=1, name="【成團】不丹", total_sales=20, stock_quantity=1)],
        )
        out = format_historical(r)
        self.assertIn("📊", out)
        self.assertIn("20 人", out)
        self.assertIn("已成團", out)
        self.assertIn("仍有 1 位候補空缺", out)

    def test_lifecycle_one_man(self):
        from wannavegtour.historical_lookup import HistoricalResult
        q = parse_query("過年那團額滿了嗎")
        r = HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_ONE, query=q,
            products=[_mkproduct(id=1, name="【額滿】過年", total_sales=36, stock_quantity=0)],
        )
        out = format_historical(r)
        self.assertIn("🔴 額滿", out)


@unittest.skipUnless(LIVE, "set HERMES_WANNAVEG_LIVE=1 to run network tests")
class TestHistoricalLive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.h = HistoricalLookup(WCClient(load_config()))

    def test_aggregate_returns_results(self):
        r = self.h.lookup(parse_query("今年賣最好的是哪些團？"))
        self.assertEqual(r.kind, HistoricalLookupKind.AGGREGATE_TOP)
        self.assertGreater(len(r.products), 0)
        # All should have positive total_sales
        for p in r.products:
            self.assertGreater(p.total_sales, 0, p.name)

    def test_specific_chengtuan_lookup(self):
        # 7/22 暑假 has a known 【成團】 product (id 241680)
        r = self.h.lookup(parse_query("7/22 暑假成團多少人？"))
        self.assertEqual(r.kind, HistoricalLookupKind.LIFECYCLE_FOUND_ONE)
        self.assertEqual(r.products[0].lifecycle_marker, "成團")

    def test_bhutan_chengtuan(self):
        r = self.h.lookup(parse_query("不丹有沒有成團"))
        self.assertIn(r.kind, (HistoricalLookupKind.LIFECYCLE_FOUND_ONE, HistoricalLookupKind.LIFECYCLE_FOUND_MANY))
        for p in r.products:
            self.assertEqual(p.lifecycle_marker, "成團")


if __name__ == "__main__":
    unittest.main()
