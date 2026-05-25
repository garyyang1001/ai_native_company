"""Format a CheckResult into a LINE-message-friendly string.

Style choices (deliberate):
  - Plain Chinese first, technical details (permalink, ID) at the end.
  - One blank line between facts, not many.
  - Emoji as visual signposts, not decoration.
  - Honest hedge when WC stock semantics can't fully answer the question.

Keep responses short — LINE users skim. Long agent monologues feel robotic.
"""

from __future__ import annotations

from .availability_checker import CheckResult, CheckResultKind
from .historical_lookup import HistoricalLookupKind, HistoricalResult
from .wc_client import (
    WCProduct,
    STOCK_LOW,
    STOCK_OK,
    STOCK_OUT,
    STOCK_UNKNOWN,
    STOCK_UNMANAGED,
)


def _format_price(p: WCProduct) -> str:
    """`NT$48,900（原價 NT$50,900）` or `NT$50,900` if no sale."""
    reg = p.regular_price
    sale = p.sale_price
    if not reg and not sale:
        return "（未定價）"
    try:
        reg_n = f"NT${int(float(reg)):,}" if reg else ""
        sale_n = f"NT${int(float(sale)):,}" if sale else ""
    except ValueError:
        return reg or sale or "（價格格式異常）"
    if sale and sale != reg:
        return f"{sale_n}（原價 {reg_n}）"
    return reg_n or sale_n


def _format_stock_line(p: WCProduct) -> str:
    bucket = p.stock_bucket
    if bucket == STOCK_OK:
        return f"✅ 名額：{p.stock_quantity} 位"
    if bucket == STOCK_LOW:
        return f"⚠️ 名額：只剩 {p.stock_quantity} 位（建議盡快確認）"
    if bucket == STOCK_OUT:
        return "❌ 名額：0 位（已售完）"
    if bucket == STOCK_UNMANAGED:
        return "ℹ️ 名額：此團未開啟庫存管理，請手動跟 OP 確認"
    return "❓ 名額：WC 沒有提供準確數字，請跟 OP 核對"


def _format_one_product(p: WCProduct) -> str:
    lines = [
        f"🎯 {p.name}",
        _format_stock_line(p),
        *([f"👥 已報名：{p.total_sales} 人"] if p.manage_stock and p.total_sales > 0 else []),
        f"💰 售價：{_format_price(p)}",
    ]
    if p.days:
        lines.append(f"📅 {p.days} 天行程")
    if p.dep_airport:
        lines.append(f"✈️ {' / '.join(p.dep_airport)}")
    lines.append(f"🔗 {p.permalink}")
    return "\n".join(lines)


def format_response(result: CheckResult) -> str:
    """Single entry point — returns the exact string the bot would post to LINE."""
    kind = result.kind

    if kind == CheckResultKind.FOUND_ONE:
        body = _format_one_product(result.products[0])
        # Honesty hedge: WC stock vs OP "actual sellable seat" can drift.
        return body + "\n\n📌 數字來自 WC 系統；若有保留位 / 候補名單請以 OP 為準。"

    if kind == CheckResultKind.FOUND_MANY:
        header = (
            f"🔍 找到 {len(result.products)} 個符合"
            f"『{result.query.destination_hint} {result.query.month}/{result.query.day}』的團，請指明是哪一個："
        )
        items = []
        for i, p in enumerate(result.products, start=1):
            stock = ""
            if p.manage_stock and p.stock_quantity is not None:
                stock = f"（剩 {p.stock_quantity} 位）"
            airport = f"［{'/'.join(p.dep_airport)}］" if p.dep_airport else ""
            items.append(f"  {i}. {airport}{p.name[:50]}{stock}\n     {p.permalink}")
        return header + "\n" + "\n".join(items) + "\n\n回 1/2/3... 我再查細節。"

    if kind == CheckResultKind.FOUND_NONE:
        return "🚫 " + "\n".join(result.advisory)

    if kind == CheckResultKind.NEED_DATE:
        return "❓ " + "\n".join(result.advisory)

    if kind == CheckResultKind.NEED_DESTINATION:
        return "❓ " + "\n".join(result.advisory)

    if kind == CheckResultKind.REFUSED_PRICE_EDIT:
        return "🙅 " + "\n".join(result.advisory)

    if kind == CheckResultKind.UNCLEAR:
        return "🤔 " + "\n".join(result.advisory)

    if kind == CheckResultKind.ERROR:
        msg = "\n".join(result.advisory)
        if result.error_message:
            msg += f"\n\n[debug] {result.error_message}"
        return "💥 " + msg

    # Defensive — should never hit, but never silently return empty.
    return f"[unknown result kind: {kind}]"


# --- historical lookup formatters -------------------------------------------

def _format_historical_one(p: WCProduct) -> str:
    """Show a single historical product with lifecycle state + sales count."""
    marker = p.lifecycle_marker
    title = p.name
    state_line = ""
    if marker == "成團":
        if p.manage_stock and p.stock_quantity is not None and p.stock_quantity > 0:
            state_line = f"狀態：✅ 已成團（仍有 {p.stock_quantity} 位候補空缺）"
        else:
            state_line = "狀態：✅ 已成團"
    elif marker == "額滿":
        state_line = "狀態：🔴 額滿（已關閉報名）"
    elif marker == "關團":
        state_line = "狀態：🔒 已關團"
    elif marker == "優質小團":
        state_line = "狀態：✨ 優質小團（特殊類型）"
    else:
        state_line = f"狀態：{p.status}（無 lifecycle marker）"

    lines = [
        f"📊 {title}",
        f"👥 報名人數：{p.total_sales} 人",
        state_line,
        f"💰 售價：{_format_price(p)}",
    ]
    if p.date_modified:
        lines.append(f"🕒 最後修改：{p.date_modified[:10]}")
    if p.permalink:
        lines.append(f"🔗 {p.permalink}")
    return "\n".join(lines)


def format_historical(result: HistoricalResult) -> str:
    """Entry point for HistoricalResult → LINE-friendly text."""
    kind = result.kind

    if kind == HistoricalLookupKind.LIFECYCLE_FOUND_ONE:
        body = _format_historical_one(result.products[0])
        return body + "\n\n📌 數字為 WC `total_sales` 生涯累計（含已退款訂單）；以 OP 紀錄為準。"

    if kind == HistoricalLookupKind.LIFECYCLE_FOUND_MANY:
        header = f"📊 找到 {len(result.products)} 個符合的歷史團（依最後修改時間排序）："
        items = []
        for i, p in enumerate(result.products, start=1):
            # name already contains the 【marker】 prefix; don't double-add.
            sales = f"{p.total_sales} 人" if p.total_sales else "0 人"
            modified = p.date_modified[:10] if p.date_modified else "—"
            items.append(f"  {i}. {p.name[:60]} — {sales}（修改：{modified}）")
            if p.permalink:
                items.append(f"     {p.permalink}")
        return header + "\n" + "\n".join(items) + "\n\n回 1/2/3... 我再查細節。"

    if kind == HistoricalLookupKind.AGGREGATE_TOP:
        year_q = result.extras.get("year_qualifier")
        scope = f"{year_q}" if year_q else "全部時段"
        header = f"🏆 {scope} wannavegtour total_sales 排行（前 {len(result.products)}）："
        items = []
        for i, p in enumerate(result.products, start=1):
            # name already contains the 【marker】 prefix; don't double-add.
            modified = p.date_modified[:10] if p.date_modified else "—"
            items.append(f"  {i}. {p.name[:60]} — 👥 {p.total_sales} 人（修改：{modified}）")
        note = result.extras.get("scope_note", "")
        body = header + "\n" + "\n".join(items)
        if note:
            body += f"\n\n📌 {note}"
        return body

    if kind == HistoricalLookupKind.CURRENT_TOUR_LIFECYCLE_STATUS:
        # User asked "成團了嗎 / 額滿了嗎" on a publish tour with no lifecycle
        # marker yet. Show current numbers; let human judge.
        lifecycle_hint = result.extras.get("lifecycle_hint") or "成團"
        if len(result.products) == 1:
            p = result.products[0]
            stock_str = (
                f"剩 {p.stock_quantity} 位"
                if p.manage_stock and p.stock_quantity is not None
                else "（未管理庫存）"
            )
            sales_str = f"目前 {p.total_sales} 人報名" if p.total_sales > 0 else "目前無人報名"
            body = (
                f"📊 {p.name}\n"
                f"👥 {sales_str}，{stock_str}\n"
                f"💰 售價：{_format_price(p)}\n"
                f"📅 還在賣中，尚未『{lifecycle_hint}』達標\n"
                f"🔗 {p.permalink}"
            )
            return body + "\n\n📌 是否算『" + lifecycle_hint + "』請以你們團規為準（WC 不知道你們設多少人成團）。"
        # Many products match — list them with sales/stock.
        header = f"📊 找到 {len(result.products)} 個符合的團（都還在賣，未『{lifecycle_hint}』達標）："
        items = []
        for i, p in enumerate(result.products, start=1):
            stock_str = (
                f"剩 {p.stock_quantity} 位"
                if p.manage_stock and p.stock_quantity is not None else "庫存未管"
            )
            sales_str = f"{p.total_sales} 人" if p.total_sales > 0 else "0 人"
            items.append(f"  {i}. {p.name[:55]}\n     👥 已報名 {sales_str}｜{stock_str}\n     {p.permalink}")
        return header + "\n" + "\n".join(items)

    if kind == HistoricalLookupKind.LIFECYCLE_FOUND_NONE:
        return "🚫 " + "\n".join(result.advisory)

    if kind == HistoricalLookupKind.NEED_QUERY_DETAIL:
        return "❓ " + "\n".join(result.advisory)

    if kind == HistoricalLookupKind.UNCLEAR:
        return "🤔 " + "\n".join(result.advisory)

    if kind == HistoricalLookupKind.ERROR:
        msg = "\n".join(result.advisory)
        if result.error_message:
            msg += f"\n\n[debug] {result.error_message}"
        return "💥 " + msg

    return f"[unknown historical kind: {kind}]"
