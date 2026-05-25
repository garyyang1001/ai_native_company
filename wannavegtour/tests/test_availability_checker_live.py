"""Live integration test against real wannavegtour.com WC API.

Skipped by default. Run with:
    HERMES_WANNAVEG_LIVE=1 python3 -m unittest wannavegtour.tests.test_availability_checker_live

These tests verify the checker against known-good products in the catalog
as of the build time. Some tests are robust to inventory drift (assert
shape, not exact stock); others are pinned to specific products that
shouldn't disappear soon (12/27 江南, 9/15 韓國首爾).
"""

from __future__ import annotations

import os
import unittest

from wannavegtour import (
    AvailabilityChecker,
    CheckResultKind,
    WCClient,
    load_config,
    parse_query,
)


LIVE = os.environ.get("HERMES_WANNAVEG_LIVE") == "1"


@unittest.skipUnless(LIVE, "set HERMES_WANNAVEG_LIVE=1 to run network tests")
class TestLive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = WCClient(load_config())
        cls.checker = AvailabilityChecker(cls.client)

    def _check(self, q: str):
        return self.checker.check(parse_query(q))

    def test_known_publish_product_found(self):
        r = self._check("12/27 江南還收嗎")
        self.assertEqual(r.kind, CheckResultKind.FOUND_ONE)
        self.assertEqual(len(r.products), 1)
        p = r.products[0]
        self.assertEqual(p.id, 255634)
        self.assertTrue(p.permalink.endswith("/product/12-27/"))

    def test_found_many_disambiguation(self):
        # 7/9 韓國首爾 has both 桃園 and 台中 departures — should return many.
        r = self._check("7/9 韓國首爾還有位嗎")
        self.assertEqual(r.kind, CheckResultKind.FOUND_MANY)
        self.assertGreaterEqual(len(r.products), 2)
        airports = [a for p in r.products for a in p.dep_airport]
        self.assertTrue(any("桃園" in a for a in airports))
        self.assertTrue(any("台中" in a for a in airports))

    def test_unknown_combination_returns_none(self):
        r = self._check("不丹 9/9 還有位嗎")
        self.assertEqual(r.kind, CheckResultKind.FOUND_NONE)

    def test_need_destination(self):
        r = self._check("3/5 那團怎麼樣？")
        self.assertEqual(r.kind, CheckResultKind.NEED_DESTINATION)

    def test_refused_price_edit(self):
        r = self._check("5/6 價格改80000")
        self.assertEqual(r.kind, CheckResultKind.REFUSED_PRICE_EDIT)

    def test_unclear(self):
        r = self._check("你好啊")
        self.assertEqual(r.kind, CheckResultKind.UNCLEAR)


if __name__ == "__main__":
    unittest.main()
