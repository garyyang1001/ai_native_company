"""Thin WooCommerce REST API client.

Single responsibility: HTTP + auth + JSON. No business logic.

All methods return native dicts / dataclasses, never raw requests.Response.
Network errors raise WCAPIError so callers can map to user-facing messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import requests

from .config import WCConfig


# Stock semantics — kept here so business logic stays declarative.
STOCK_UNMANAGED = "unmanaged"   # manage_stock=False (no count tracked)
STOCK_OUT = "out"               # manage_stock=True, stock_quantity == 0
STOCK_LOW = "low"               # 1..3
STOCK_OK = "ok"                 # >=4
STOCK_UNKNOWN = "unknown"       # missing data


class WCAPIError(RuntimeError):
    """Raised on any failure talking to the WC REST API (network, 4xx, 5xx)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WCProduct:
    """The subset of WC product fields we use. Frozen so it's hashable + safe."""
    id: int
    name: str
    slug: str
    status: str
    permalink: str
    regular_price: str
    sale_price: str
    stock_quantity: int | None
    manage_stock: bool
    stock_status: str
    total_sales: int                 # WC's lifetime sold count — proxy for 報名人數
    date_modified: str               # ISO timestamp, last edit
    departure_date: str | None       # YYYYMMDD from meta
    departure_month: str | None      # "12月" from meta
    days: str | None                 # "6" from meta
    dep_airport: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    @property
    def lifecycle_marker(self) -> str | None:
        """Extract leading 【X】 marker from name if it matches a known lifecycle tag."""
        from .query_parser import LIFECYCLE_MARKERS  # local import avoids cycle
        for m in LIFECYCLE_MARKERS:
            if self.name.startswith(f"【{m}】"):
                return m
        return None

    @property
    def stock_bucket(self) -> str:
        """Map raw stock fields to a discrete bucket business code can switch on."""
        if not self.manage_stock:
            return STOCK_UNMANAGED
        if self.stock_quantity is None:
            return STOCK_UNKNOWN
        if self.stock_quantity == 0:
            return STOCK_OUT
        if self.stock_quantity <= 3:
            return STOCK_LOW
        return STOCK_OK

    @property
    def is_on_sale(self) -> bool:
        return bool(self.sale_price) and self.sale_price != self.regular_price

    @property
    def display_price(self) -> str:
        """The price a customer would actually pay (sale if active, else regular)."""
        return self.sale_price if self.is_on_sale else self.regular_price


def _meta_lookup(meta_data: list[dict[str, Any]], key: str) -> Any:
    for m in meta_data:
        if m.get("key") == key:
            return m.get("value")
    return None


def _meta_as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if v in (None, "", False):
        return []
    return [str(v)]


def _product_from_raw(raw: dict[str, Any]) -> WCProduct:
    meta = raw.get("meta_data") or []
    try:
        total_sales_int = int(raw.get("total_sales") or 0)
    except (TypeError, ValueError):
        total_sales_int = 0
    return WCProduct(
        id=int(raw["id"]),
        name=raw.get("name", ""),
        slug=raw.get("slug", ""),
        status=raw.get("status", ""),
        permalink=raw.get("permalink", ""),
        regular_price=str(raw.get("regular_price") or ""),
        sale_price=str(raw.get("sale_price") or ""),
        stock_quantity=raw.get("stock_quantity"),
        manage_stock=bool(raw.get("manage_stock")),
        stock_status=raw.get("stock_status", ""),
        total_sales=total_sales_int,
        date_modified=str(raw.get("date_modified") or ""),
        departure_date=(str(_meta_lookup(meta, "departure-date")) if _meta_lookup(meta, "departure-date") else None),
        departure_month=(str(_meta_lookup(meta, "departure_month")) if _meta_lookup(meta, "departure_month") else None),
        days=(str(_meta_lookup(meta, "days")) if _meta_lookup(meta, "days") else None),
        dep_airport=_meta_as_str_list(_meta_lookup(meta, "dep_airport")),
        categories=[c.get("name", "") for c in (raw.get("categories") or [])],
    )


class WCClient:
    """Thin synchronous WC REST client. Reuses one requests.Session."""

    DEFAULT_TIMEOUT = 15  # seconds

    def __init__(self, config: WCConfig, timeout: float | None = None) -> None:
        self.config = config
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._session = requests.Session()
        self._session.auth = (config.consumer_key, config.consumer_secret)
        self._session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.api_root}/{path.lstrip('/')}"
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise WCAPIError(f"network error talking to {url}: {e}") from e
        if r.status_code == 401:
            raise WCAPIError("401 Unauthorized — check WC credentials", 401)
        if r.status_code == 403:
            raise WCAPIError("403 Forbidden — credential lacks read permission", 403)
        if r.status_code >= 400:
            raise WCAPIError(f"HTTP {r.status_code} from {url}: {r.text[:200]}", r.status_code)
        try:
            return r.json()
        except ValueError as e:
            raise WCAPIError(f"non-JSON response from {url}: {r.text[:200]}") from e

    def search_products(
        self,
        *,
        search: str | None = None,
        status: str | Iterable[str] = "publish",
        per_page: int = 50,
        page: int = 1,
        orderby: str | None = None,
        order: str = "desc",
    ) -> list[WCProduct]:
        """List products.

        `status` is one of WC's accepted single values
        (`publish` / `private` / `draft` / `pending` / `future` / `trash` / `any`)
        OR an iterable of those — in which case we fan out one request per status
        and merge + de-dupe by product id. The WC REST API does NOT support
        comma-separated multi-status query, so multi-status MUST go through fan-out.
        """
        if not isinstance(status, str):
            seen: dict[int, WCProduct] = {}
            for s in status:
                for p in self.search_products(
                    search=search, status=s, per_page=per_page, page=page,
                    orderby=orderby, order=order,
                ):
                    seen[p.id] = p
            return list(seen.values())

        params: dict[str, Any] = {"per_page": per_page, "page": page, "status": status}
        if search:
            params["search"] = search
        if orderby is not None:
            params["orderby"] = orderby
            params["order"] = order
        raw = self._get("products", params=params)
        if not isinstance(raw, list):
            raise WCAPIError(f"expected list from /products, got {type(raw).__name__}")
        return [_product_from_raw(r) for r in raw]

    def get_product(self, product_id: int) -> WCProduct:
        """Single product fetch — returns full meta_data populated WCProduct."""
        raw = self._get(f"products/{product_id}")
        if not isinstance(raw, dict):
            raise WCAPIError(f"expected object from /products/{product_id}, got {type(raw).__name__}")
        return _product_from_raw(raw)
