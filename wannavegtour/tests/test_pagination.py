"""Tests for paginated WC search behavior
(codex review 2026-05-25 P1 + P2 — pagination fixes)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from wannavegtour import (
    AvailabilityChecker,
    CheckResultKind,
    HistoricalLookup,
    HistoricalLookupKind,
    parse_query,
)
from wannavegtour.wc_client import WCClient, WCProduct


def _mkproduct(id: int, name: str, departure_date: str | None = None, status: str = "publish"):
    return WCProduct(
        id=id, name=name, slug=f"p-{id}", status=status,
        permalink=f"https://x/p-{id}/",
        regular_price="50000", sale_price="",
        stock_quantity=10, manage_stock=True, stock_status="instock",
        total_sales=5, date_modified="2026-05-01T00:00:00",
        departure_date=departure_date,
        departure_month=None, days=None, dep_airport=[], categories=[],
    )


class TestAvailabilityPagination(unittest.TestCase):
    """Codex P1: previously, only page 1 was fetched. A match on page 2 was
    silently dropped, returning FOUND_NONE despite the product existing."""

    def test_match_on_page_2_is_found(self):
        client = MagicMock(spec=WCClient)
        # Page 1: 30 products none of which match 0305
        page1 = [_mkproduct(i, f"product {i}", departure_date="20260101") for i in range(1, 31)]
        # Page 2: contains the matching product
        page2 = [_mkproduct(99, "3/5 江南", departure_date="20260305")]
        # Page 3+: empty
        def side_effect(*, search=None, status="publish", per_page=50, page=1):
            return {1: page1, 2: page2}.get(page, [])
        client.search_products.side_effect = side_effect

        checker = AvailabilityChecker(client)
        result = checker.check(parse_query("3/5 江南還收嗎"))
        self.assertEqual(result.kind, CheckResultKind.FOUND_ONE)
        self.assertEqual(result.products[0].id, 99)

    def test_stops_when_batch_smaller_than_per_page(self):
        # Page 1: full batch of 30 → continue; Page 2: 5 products → stop.
        # Verifies the early-exit pagination heuristic.
        client = MagicMock(spec=WCClient)
        page1 = [_mkproduct(i, f"product {i}", departure_date="20260101") for i in range(1, 31)]
        page2 = [_mkproduct(50, "page2 a"), _mkproduct(51, "page2 b")]
        calls = []
        def side_effect(*, search=None, status="publish", per_page=50, page=1):
            calls.append(page)
            return {1: page1, 2: page2}.get(page, [])
        client.search_products.side_effect = side_effect

        checker = AvailabilityChecker(client)
        checker.check(parse_query("3/5 江南"))
        # Should call page 1, then page 2 (returns less than per_page), then stop.
        self.assertEqual(calls, [1, 2])

    def test_hard_cap_at_search_max_pages(self):
        # Every page returns full batch — pagination must stop at SEARCH_MAX_PAGES.
        client = MagicMock(spec=WCClient)
        full = [_mkproduct(i, f"product {i}", departure_date="20260101") for i in range(1, 31)]
        calls = []
        def side_effect(*, search=None, status="publish", per_page=50, page=1):
            calls.append(page)
            return full
        client.search_products.side_effect = side_effect

        checker = AvailabilityChecker(client)
        checker.check(parse_query("3/5 江南"))
        # Must not exceed AvailabilityChecker.SEARCH_MAX_PAGES
        self.assertEqual(len(calls), checker.SEARCH_MAX_PAGES)


class TestHistoricalPagination(unittest.TestCase):
    """Codex P2: same pagination bug for historical destination-based lookups."""

    def test_destination_search_paginates_per_status(self):
        client = MagicMock(spec=WCClient)
        full = [_mkproduct(i, f"product {i}", departure_date="20250722") for i in range(1, 31)]
        calls: list[tuple] = []
        def side_effect(*, search=None, status="publish", per_page=50, page=1):
            calls.append((status, page))
            return full
        client.search_products.side_effect = side_effect

        h = HistoricalLookup(client)
        # destination_hint set ("不丹") → fan out per status with pagination
        h.lookup(parse_query("不丹有沒有成團"))
        # 3 statuses × SEARCH_MAX_PAGES pages each
        statuses_called = {c[0] for c in calls}
        self.assertEqual(statuses_called, {"publish", "private", "draft"})
        pages_per_status = max(c[1] for c in calls)
        self.assertEqual(pages_per_status, h.SEARCH_MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
