"""Type 1 (查名額) worker.

Composes a parsed query + WCClient into a CheckResult. No I/O of its own —
all WC calls go through WCClient (so tests can inject a fake).

Algorithm:
    1. If intent is PRICE_EDIT_HINT or UNCLEAR → return early with reason.
    2. If no destination_hint → ask user to clarify which 目的地.
    3. Search WC: `?search={destination_hint}&status=publish`.
    4. Filter by departure_date_mmdd against each product's `departure-date` meta.
    5. Bucket: 0 / 1 / many → corresponding CheckResultKind.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .query_parser import ParsedQuery, QueryIntent
from .wc_client import WCClient, WCProduct, WCAPIError


class CheckResultKind(str, enum.Enum):
    FOUND_ONE = "found_one"
    FOUND_MANY = "found_many"
    FOUND_NONE = "found_none"
    NEED_DESTINATION = "need_destination"      # date present but no destination_hint
    NEED_DATE = "need_date"                    # destination present but no date
    REFUSED_PRICE_EDIT = "refused_price_edit"  # Type 2 — not in this slice
    UNCLEAR = "unclear"
    ERROR = "error"                            # network / API failure


@dataclass(frozen=True)
class CheckResult:
    kind: CheckResultKind
    query: ParsedQuery
    products: list[WCProduct] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    error_message: str | None = None

    @property
    def is_actionable(self) -> bool:
        return self.kind in (CheckResultKind.FOUND_ONE, CheckResultKind.FOUND_MANY)


class AvailabilityChecker:
    # Per-page batch size when paginating WC search.
    SEARCH_PER_PAGE = 30
    # Hard cap on total pages fetched per query — bounds worst-case latency
    # for broad searches like country names that match many products.
    SEARCH_MAX_PAGES = 4   # 4 * 30 = 120 products max per query

    def __init__(self, client: WCClient) -> None:
        self.client = client

    def check(self, query: ParsedQuery) -> CheckResult:
        # 1. Early refusals.
        if query.intent == QueryIntent.PRICE_EDIT_HINT:
            return CheckResult(
                kind=CheckResultKind.REFUSED_PRICE_EDIT, query=query,
                advisory=["這看起來是改價/改資訊指令（Type 2），本切片只處理 Type 1 查名額。請手動處理或等 Type 2 worker 上線。"],
            )
        if query.intent == QueryIntent.UNCLEAR:
            return CheckResult(
                kind=CheckResultKind.UNCLEAR, query=query,
                advisory=["訊息不明確：找不到日期或關鍵字。例：『3/5 峴港還剩多少？』"],
            )

        # 2. Validate inputs for Type 1.
        if not query.has_date:
            return CheckResult(
                kind=CheckResultKind.NEED_DATE, query=query,
                advisory=["請補上出發日，例：『3/5』或『3月5日』。"],
            )
        if not query.destination_hint:
            return CheckResult(
                kind=CheckResultKind.NEED_DESTINATION, query=query,
                advisory=["請補上目的地關鍵字，例：『峴港』、『江南』。"],
            )

        # 3. Search with pagination — broad destinations (e.g. "韓國") can match
        # more products than SEARCH_PER_PAGE; reading only page 1 can silently
        # miss a date hit on later pages and return FOUND_NONE incorrectly.
        try:
            candidates: list = []
            for page in range(1, self.SEARCH_MAX_PAGES + 1):
                batch = self.client.search_products(
                    search=query.destination_hint,
                    status="publish",
                    per_page=self.SEARCH_PER_PAGE,
                    page=page,
                )
                candidates.extend(batch)
                if len(batch) < self.SEARCH_PER_PAGE:
                    break
        except WCAPIError as e:
            return CheckResult(
                kind=CheckResultKind.ERROR, query=query, error_message=str(e),
                advisory=["WooCommerce API 出錯，無法回答。請手動查或稍後再試。"],
            )

        # 4. Filter by departure_date_mmdd (and full date when year is known).
        mmdd = query.departure_date_mmdd
        full = query.departure_date_full

        # search returned products may not include meta_data depending on WC version.
        # Re-fetch each candidate by id to guarantee departure_date is populated.
        # Cap at SEARCH_MAX_PAGES * SEARCH_PER_PAGE total enrichments.
        enrich_cap = self.SEARCH_PER_PAGE * self.SEARCH_MAX_PAGES
        enriched: list[WCProduct] = []
        for c in candidates[:enrich_cap]:
            if c.departure_date:
                enriched.append(c)
                continue
            try:
                full_product = self.client.get_product(c.id)
            except WCAPIError:
                # Skip products we can't enrich; don't fail the whole query.
                continue
            enriched.append(full_product)

        # Exact full-date wins; fallback to MMDD any-year if exact missing.
        exact = [p for p in enriched if full and p.departure_date == full]
        if exact:
            matches = exact
        else:
            matches = [p for p in enriched if p.departure_date and p.departure_date.endswith(mmdd)] if mmdd else []

        # 5. Bucket.
        if len(matches) == 0:
            return CheckResult(
                kind=CheckResultKind.FOUND_NONE, query=query, products=[],
                advisory=[
                    f"查不到出發日 {query.month}/{query.day} 含『{query.destination_hint}』的上架團。",
                    "可能：尚未上架（在 private/draft 草稿）、日期打錯、或目的地關鍵字不在標題中。",
                ],
            )
        if len(matches) == 1:
            return CheckResult(kind=CheckResultKind.FOUND_ONE, query=query, products=matches)
        return CheckResult(kind=CheckResultKind.FOUND_MANY, query=query, products=matches)
