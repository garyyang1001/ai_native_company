"""Type 3/4-lite worker: historical / lifecycle / aggregate lookup.

Queries this worker handles:
    - "7/22 暑假成團多少人？"         → LIFECYCLE_FOUND_ONE (specific tour)
    - "過年那團最後額滿了嗎？"        → LIFECYCLE_FOUND_ONE or MANY (lifecycle question)
    - "今年賣最好的是哪些團？"         → AGGREGATE_TOP (ranking by total_sales)
    - "去年賣最多的團"                → AGGREGATE_TOP (filtered by year)
    - "不丹有沒有成團"                → LIFECYCLE_FOUND_MANY by destination + marker

Key distinction from AvailabilityChecker:
    - Searches across publish + private + draft (lifecycle markers live on private)
    - Uses `total_sales` as the primary metric (= 報名人數), not `stock_quantity`
    - Filters by lifecycle marker prefix in product name (【成團】/【額滿】/【關團】)
    - For aggregate: NO per-product enrichment (would be 400+ round trips); uses
      list-endpoint fields + `date_modified` as a proxy for "this year".

Honest hedges:
    - "今年" / "去年" filters use date_modified (last edit), NOT departure_date.
      A tour edited recently for re-launch could mislead. Formatter calls this out.
    - total_sales is WC's lifetime sold count, including refunded orders.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field

from .query_parser import LIFECYCLE_MARKERS, ParsedQuery, QueryIntent
from .wc_client import WCAPIError, WCClient, WCProduct


# All product statuses we fan out across for historical queries.
_ALL_STATUSES = ("publish", "private", "draft")

# Top-N for aggregate queries.
_AGGREGATE_TOP_N = 10

# Hard cap on aggregate pull to keep latency bounded (~5 pages × 100).
_AGGREGATE_MAX_PAGES = 5
_AGGREGATE_PER_PAGE = 100


class HistoricalLookupKind(str, enum.Enum):
    LIFECYCLE_FOUND_ONE = "lifecycle_found_one"
    LIFECYCLE_FOUND_MANY = "lifecycle_found_many"
    LIFECYCLE_FOUND_NONE = "lifecycle_found_none"
    AGGREGATE_TOP = "aggregate_top"
    NEED_QUERY_DETAIL = "need_query_detail"        # 太模糊
    UNCLEAR = "unclear"
    ERROR = "error"


@dataclass(frozen=True)
class HistoricalResult:
    kind: HistoricalLookupKind
    query: ParsedQuery
    products: list[WCProduct] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    error_message: str | None = None
    # extras carry route-specific info for formatter (year_qualifier, lifecycle_hint, etc.)
    extras: dict = field(default_factory=dict)


class HistoricalLookup:
    """Worker for HISTORICAL_LOOKUP intent queries."""

    SEARCH_PER_PAGE = 30
    # Hard cap on pages fetched per (search, status) — broad destinations
    # like "韓國" have lifecycle products spread across many years.
    SEARCH_MAX_PAGES = 4

    def __init__(self, client: WCClient) -> None:
        self.client = client

    # --- public entry --------------------------------------------------------

    def lookup(self, query: ParsedQuery) -> HistoricalResult:
        if query.intent != QueryIntent.HISTORICAL_LOOKUP:
            return HistoricalResult(
                kind=HistoricalLookupKind.UNCLEAR, query=query,
                advisory=[f"非 HISTORICAL_LOOKUP intent ({query.intent.value})，請走對應 worker。"],
            )

        extras = query.extras or {}
        is_aggregate = bool(extras.get("is_aggregate"))
        lifecycle_hint = extras.get("lifecycle_hint")
        year_qualifier = extras.get("year_qualifier")

        if is_aggregate:
            return self._aggregate(query, year_qualifier=year_qualifier)

        return self._specific(query, lifecycle_hint=lifecycle_hint, year_qualifier=year_qualifier)

    # --- aggregate path ------------------------------------------------------

    def _aggregate(self, query: ParsedQuery, *, year_qualifier: str | None) -> HistoricalResult:
        """Fan out + rank by total_sales desc. No per-product enrichment."""
        try:
            collected = self._fan_out_all_statuses()
        except WCAPIError as e:
            return HistoricalResult(
                kind=HistoricalLookupKind.ERROR, query=query, error_message=str(e),
                advisory=["WC API 出錯，無法計算 ranking。"],
            )

        # Year filter using date_modified ISO timestamp.
        if year_qualifier:
            year_target = self._resolve_year_target(year_qualifier)
            if year_target is not None:
                collected = [p for p in collected if p.date_modified.startswith(str(year_target))]

        # Rank by total_sales desc; tiebreak by date_modified desc.
        collected.sort(key=lambda p: (p.total_sales, p.date_modified), reverse=True)
        top = [p for p in collected if p.total_sales > 0][:_AGGREGATE_TOP_N]

        if not top:
            return HistoricalResult(
                kind=HistoricalLookupKind.LIFECYCLE_FOUND_NONE, query=query,
                advisory=[
                    "找不到任何 total_sales > 0 的團"
                    + (f"（{year_qualifier} 範圍內）" if year_qualifier else "") + "。",
                ],
                extras={"year_qualifier": year_qualifier},
            )

        return HistoricalResult(
            kind=HistoricalLookupKind.AGGREGATE_TOP, query=query, products=top,
            extras={
                "year_qualifier": year_qualifier,
                "scope_note": "排序依 WC `total_sales`（生涯累計報名人數，含已退款）"
                              + (f"；範圍依 date_modified 在 {year_qualifier}" if year_qualifier else ""),
            },
        )

    # --- specific lookup path ------------------------------------------------

    def _specific(
        self, query: ParsedQuery, *, lifecycle_hint: str | None, year_qualifier: str | None,
    ) -> HistoricalResult:
        """Find specific tour(s) matching destination + date + lifecycle marker."""
        # We need either a destination_hint OR a date to do a meaningful search.
        if not query.destination_hint and not query.has_date:
            return HistoricalResult(
                kind=HistoricalLookupKind.NEED_QUERY_DETAIL, query=query,
                advisory=["請補上目的地或日期，例：『過年那團』、『7/22 暑假』、『不丹』。"],
            )

        # Use destination_hint as WC search term. If only a date is given,
        # we can't search by departure-date in the WC list endpoint (no meta_query
        # without extra plugins) — fall back to fetching all + filtering client-side.
        try:
            candidates: list[WCProduct] = []
            if query.destination_hint:
                # Paginate per status — common destinations have many lifecycle
                # products spread across years. SEARCH_MAX_PAGES caps round-trips.
                for status in _ALL_STATUSES:
                    for page in range(1, self.SEARCH_MAX_PAGES + 1):
                        batch = self.client.search_products(
                            search=query.destination_hint, status=status,
                            per_page=self.SEARCH_PER_PAGE, page=page,
                        )
                        candidates.extend(batch)
                        if len(batch) < self.SEARCH_PER_PAGE:
                            break
            else:
                # date-only — pull all, filter by departure-date afterwards.
                candidates = self._fan_out_all_statuses()
        except WCAPIError as e:
            return HistoricalResult(
                kind=HistoricalLookupKind.ERROR, query=query, error_message=str(e),
                advisory=["WC API 出錯，無法查詢。"],
            )

        # De-dupe by id (the same product won't repeat across statuses, but safe).
        by_id: dict[int, WCProduct] = {p.id: p for p in candidates}
        candidates = list(by_id.values())

        # Enrich only those that lack departure_date AND a date filter is needed.
        if query.has_date:
            enriched: list[WCProduct] = []
            for c in candidates:
                if c.departure_date:
                    enriched.append(c)
                    continue
                try:
                    enriched.append(self.client.get_product(c.id))
                except WCAPIError:
                    continue
            candidates = enriched

            mmdd = query.departure_date_mmdd
            full = query.departure_date_full
            exact = [p for p in candidates if full and p.departure_date == full]
            candidates = exact if exact else [
                p for p in candidates if p.departure_date and mmdd and p.departure_date.endswith(mmdd)
            ]

        # Filter by lifecycle marker if user mentioned one (成團/額滿/關團).
        if lifecycle_hint:
            candidates = [p for p in candidates if p.lifecycle_marker == lifecycle_hint]

        # Filter by year_qualifier (uses departure_date if present, else date_modified).
        if year_qualifier:
            year_target = self._resolve_year_target(year_qualifier)
            if year_target is not None:
                def in_year(p: WCProduct) -> bool:
                    if p.departure_date and len(p.departure_date) >= 4:
                        return p.departure_date.startswith(str(year_target))
                    return p.date_modified.startswith(str(year_target))
                candidates = [p for p in candidates if in_year(p)]

        # Bucket.
        if not candidates:
            advisory = [
                "查不到符合條件的歷史團。",
                "可能：(a) 標題前綴 marker 不在 [成團/額滿/關團/優質小團] 之列，"
                "(b) 沒有 lifecycle marker（純草稿），(c) 日期 / 目的地 / 年份組合對不上。",
            ]
            return HistoricalResult(
                kind=HistoricalLookupKind.LIFECYCLE_FOUND_NONE, query=query, advisory=advisory,
            )
        if len(candidates) == 1:
            return HistoricalResult(
                kind=HistoricalLookupKind.LIFECYCLE_FOUND_ONE, query=query, products=candidates,
            )

        # Many — sort by date_modified desc so most-recent shows first.
        candidates.sort(key=lambda p: p.date_modified, reverse=True)
        return HistoricalResult(
            kind=HistoricalLookupKind.LIFECYCLE_FOUND_MANY, query=query, products=candidates[:10],
        )

    # --- helpers -------------------------------------------------------------

    def _fan_out_all_statuses(self) -> list[WCProduct]:
        """Pull all publish + private + draft, paginated. De-dupes by product id
        so callers can blindly sort / aggregate without worrying about cross-call
        duplication (a real concern with mock clients; defensive in production)."""
        by_id: dict[int, WCProduct] = {}
        for status in _ALL_STATUSES:
            for page in range(1, _AGGREGATE_MAX_PAGES + 1):
                batch = self.client.search_products(
                    status=status, per_page=_AGGREGATE_PER_PAGE, page=page,
                )
                for p in batch:
                    by_id[p.id] = p
                if len(batch) < _AGGREGATE_PER_PAGE:
                    break
        return list(by_id.values())

    def _resolve_year_target(self, qualifier: str, today: dt.date | None = None) -> int | None:
        """Translate '今年' / '去年' / '前年' / '歷年' to a year integer or None for歷年."""
        today = today or dt.date.today()
        if qualifier in ("今年", "近期", "近幾"):
            return today.year
        if qualifier == "去年":
            return today.year - 1
        if qualifier == "前年":
            return today.year - 2
        # 歷年 / 其他 → no year filter
        return None
