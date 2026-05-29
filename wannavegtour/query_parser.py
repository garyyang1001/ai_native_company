"""Parse LINE-style OP-group messages into structured queries.

Code-is-Law: pure deterministic rules, no LLM. Every output is reproducible
from the same input.

Scope of this slice: Type 1 availability questions. Type 2/3/4 are detected
as PRICE_EDIT_HINT / UNCLEAR so the worker can refuse early instead of
hallucinating an answer.

Real OP-group examples this parser must handle:
    "3/5 那團怎麼樣？還剩多少？"
    "5/6 價格改80000"          → PRICE_EDIT_HINT (refuse, not Type 1)
    "5/6 價格改8萬"             → PRICE_EDIT_HINT (refuse, not Type 1)
    "峴港3-15還有位嗎"
    "請問１２/２７ 那團"        → full-width digits
    "12月27日 江南還收嗎"
    "下週的不丹團還有空位嗎"    → defer (no concrete date, treat as UNCLEAR)
"""

from __future__ import annotations

import datetime as dt
import enum
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


class QueryIntent(str, enum.Enum):
    AVAILABILITY_CHECK = "availability_check"        # Type 1: 賣中、查名額
    HISTORICAL_LOOKUP = "historical_lookup"          # Type 3/4 lite: 已成團 / 額滿 / 賣最好
    PRICE_EDIT_HINT = "price_edit_hint"              # Type 2 indicator; this slice refuses
    UNCLEAR = "unclear"


# Lifecycle prefix markers used in the team's WP product titles to signal
# group state. The team uses `status=private` as the workflow stage holder
# and these prefixes as the state marker.
LIFECYCLE_MARKERS = ("成團", "關團", "額滿", "優質小團", "徵團")


@dataclass(frozen=True)
class ParsedQuery:
    raw_text: str
    intent: QueryIntent
    month: int | None
    day: int | None
    destination_hint: str | None
    matched_year: int | None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def has_date(self) -> bool:
        return self.month is not None and self.day is not None

    @property
    def departure_date_mmdd(self) -> str | None:
        """The MMDD suffix used to match against WC `departure-date` meta (YYYYMMDD)."""
        if not self.has_date:
            return None
        return f"{self.month:02d}{self.day:02d}"

    @property
    def departure_date_full(self) -> str | None:
        """Full YYYYMMDD with inferred year, for exact-match queries."""
        if not self.has_date or self.matched_year is None:
            return None
        return f"{self.matched_year}{self.month:02d}{self.day:02d}"


# --- text normalization -----------------------------------------------------

_FULLWIDTH_DIGIT_MAP = {chr(0xFF10 + i): str(i) for i in range(10)}
_FULLWIDTH_SLASH_MAP = {"／": "/", "－": "-", "．": ".", "　": " "}

_CN_NUM_MAP = {
    "零": 0, "〇": 0, "○": 0,
    "一": 1, "壹": 1,
    "二": 2, "兩": 2, "貳": 2,
    "三": 3, "參": 3,
    "四": 4, "肆": 4,
    "五": 5, "伍": 5,
    "六": 6, "陸": 6,
    "七": 7, "柒": 7,
    "八": 8, "捌": 8,
    "九": 9, "玖": 9,
    "十": 10, "拾": 10,
}


def _normalize(text: str) -> str:
    """Half-width digits, common separators, NFKC."""
    text = unicodedata.normalize("NFKC", text)
    for k, v in _FULLWIDTH_DIGIT_MAP.items():
        text = text.replace(k, v)
    for k, v in _FULLWIDTH_SLASH_MAP.items():
        text = text.replace(k, v)
    return text


def _parse_chinese_number(s: str) -> int | None:
    """Parse 1-31 in Chinese (e.g. 三 → 3, 十二 → 12, 二十五 → 25, 三十一 → 31)."""
    if not s:
        return None
    if s in _CN_NUM_MAP:
        return _CN_NUM_MAP[s]
    # 十X (10+X)
    if s.startswith("十") and len(s) == 2 and s[1] in _CN_NUM_MAP:
        return 10 + _CN_NUM_MAP[s[1]]
    # X十 (X*10)
    if len(s) == 2 and s.endswith("十") and s[0] in _CN_NUM_MAP:
        return _CN_NUM_MAP[s[0]] * 10
    # X十Y (X*10+Y)
    if len(s) == 3 and s[1] == "十" and s[0] in _CN_NUM_MAP and s[2] in _CN_NUM_MAP:
        return _CN_NUM_MAP[s[0]] * 10 + _CN_NUM_MAP[s[2]]
    return None


# --- date extraction --------------------------------------------------------

_DATE_PATTERNS = [
    # 12/27, 3-5, 3.5  (Arabic digits)
    re.compile(r"(?<![0-9])([0-9]{1,2})[/.\-]([0-9]{1,2})(?:號|号)?"),
    # 12月27日, 3月5號
    re.compile(r"([0-9]{1,2})月([0-9]{1,2})(?:日|號|号)"),
    # 十二月二十七日, 三月五號 (Chinese digits + 月 + 日/號)
    re.compile(r"([零〇○一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]{1,3})月([零〇○一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]{1,4})(?:日|號|号)"),
]


def _extract_date(normalized: str) -> tuple[int | None, int | None, str | None]:
    """Returns (month, day, matched_substring) or (None, None, None)."""
    for pat in _DATE_PATTERNS:
        m = pat.search(normalized)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        # Numeric or Chinese?
        if a.isdigit():
            month, day = int(a), int(b)
        else:
            month = _parse_chinese_number(a)
            day = _parse_chinese_number(b)
        if month is None or day is None:
            continue
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day, m.group(0)
    return None, None, None


def _infer_year(month: int, day: int, today: dt.date | None = None) -> int:
    """If the (month, day) has already passed this year, assume next year."""
    today = today or dt.date.today()
    candidate = today.year
    try:
        d = dt.date(candidate, month, day)
    except ValueError:
        # Invalid date (e.g. 2/30) — caller validates upstream, fallback to current year.
        return candidate
    if d < today:
        return candidate + 1
    return candidate


# --- intent detection -------------------------------------------------------

_AVAILABILITY_KEYWORDS = (
    "還有", "還剩", "剩多少", "剩幾", "剩下", "多少",
    "還收", "還能報", "還能不能", "有沒有位", "有位", "空位",
    "名額", "位置", "幾位", "幾個",
    "怎麼樣", "如何", "情況",        # 「3/5 那團怎麼樣」常見問法
    "那團", "這團",                  # implicit「告訴我這團情況」
)

# Words that mean "edit / change price" — strong Type 2 signal.
_PRICE_EDIT_KEYWORDS = (
    "改成", "改為", "改價", "改售價", "調成", "調整成", "改",
)

# Money-like signals (amount-with-unit) for Type 2 detection.
_MONEY_PATTERNS = [
    re.compile(r"[0-9]+[,，][0-9]+"),     # 80,000 / 80，000
    re.compile(r"[0-9]+\s*萬"),            # 8萬 / 8 萬
    re.compile(r"[0-9]{4,}"),              # 80000+
    re.compile(r"NT\$\s*[0-9]+", re.IGNORECASE),
]


def _looks_like_price_edit(normalized: str) -> bool:
    if not any(kw in normalized for kw in _PRICE_EDIT_KEYWORDS):
        return False
    return any(p.search(normalized) for p in _MONEY_PATTERNS)


def _has_availability_keyword(normalized: str) -> bool:
    return any(kw in normalized for kw in _AVAILABILITY_KEYWORDS)


# --- historical lookup signals ----------------------------------------------

# Past-tense indicators — these flip availability questions into historical.
_PAST_TENSE_KEYWORDS = (
    "上次", "上回", "之前", "最後", "那次", "後來", "結果",
)

# Aggregate / ranking questions. Watch for spoken-style variants with 的 / 得
# in the middle ("賣的最好", "賣得最好") — those don't match strict substring
# of "賣最好" because of the inserted character. Be liberal.
_AGGREGATE_KEYWORDS = (
    "賣最好", "賣得最好", "賣的最好",
    "賣最多", "賣得最多", "賣的最多",
    "賣得最", "賣得多",
    "最多人",
    "排行", "前幾", "Top", "top",
)

# Year qualifier — pure rough match, HistoricalLookup decides the actual range.
_YEAR_QUALIFIERS = ("今年", "去年", "前年", "歷年", "近期", "近幾", "最近")

# NOTE: We deliberately do NOT keep a "lifecycle question keywords" list with
# ambiguous tokens like "報名" / "多少人" / "幾人" / "人數". Those words appear
# in current-state availability queries too ("還能報名嗎", "還剩多少人") and
# unconditionally routing them to historical caused false positives — surfaced
# by codex review 2026-05-25. Lifecycle detection now relies solely on:
#   - lifecycle_hint (presence of 成團/額滿/關團/優質小團/徵團 markers)
#   - past-tense keywords
#   - aggregate keywords
# Person-count phrasing routes correctly via the lifecycle_hint or past-tense
# signal when historical context is present, and stays in AVAILABILITY_CHECK
# otherwise.


def _detect_lifecycle_hint(normalized: str) -> str | None:
    """Returns first lifecycle marker mentioned in the text (e.g. '成團')."""
    for marker in LIFECYCLE_MARKERS:
        if marker in normalized:
            return marker
    return None


def _detect_year_qualifier(normalized: str) -> str | None:
    for q in _YEAR_QUALIFIERS:
        if q in normalized:
            return q
    return None


def _is_aggregate_query(normalized: str) -> bool:
    return any(kw in normalized for kw in _AGGREGATE_KEYWORDS)


def _is_historical_query(normalized: str, lifecycle_hint: str | None, is_aggregate: bool) -> bool:
    """Historical if any of: past-tense word, lifecycle marker, aggregate keyword."""
    if is_aggregate:
        return True
    if lifecycle_hint is not None:
        return True
    if any(kw in normalized for kw in _PAST_TENSE_KEYWORDS):
        return True
    return False


# --- destination hint extraction --------------------------------------------

# Tokens stripped before residue is sent to WC `?search=`.
# Order matters: longer patterns first so they win over shorter substrings.
# (e.g. "還剩多少" must precede "剩多少" must precede "多少", otherwise the
# shorter one strips first and orphans like "還" leak through.)
_STRIP_TOKENS = [
    # 4-char combined phrases
    "還剩多少", "還能不能", "還能報名", "有沒有位",
    # 3-char phrases
    "問一下", "怎麼樣", "剩多少", "還能報",
    "有沒有", "是哪些", "賣最好", "賣最多", "賣得最",
    "優質小團",
    # 2-char phrases — filler / question / availability
    "那團", "這團", "請問", "想問", "幫忙",
    "如何", "情況",
    "還剩", "還有", "剩幾", "剩下", "還收",
    "有位", "空位", "名額", "位置", "幾位", "幾個",
    "多少",
    # historical lifecycle keywords — leave to extras.lifecycle_hint
    "成團", "額滿", "關團", "報名", "幾人", "人數",
    # historical filler
    "最後", "上次", "上回", "之前", "那次", "後來", "結果",
    "了嗎", "哪些", "前幾",
    # year qualifiers — extras.year_qualifier holds them
    "今年", "去年", "前年", "歷年", "近期", "近幾",
    # date-relative noise (for future smarter date parsing)
    "下個月", "上個月", "這個月",
    "下週", "上週", "本週", "明天", "後天", "今天",
    "的",
    # 1-char filler — runs LAST so multi-char tokens above win first.
    # CAUTION: do NOT add "成" alone (would break 成都); "人" is safe (no dest
    # uses it in this catalog; 仁川 uses 仁 U+4EC1, not 人).
    "嗎", "呢", "啊", "喔", "ㄛ", "唷", "團", "位", "還", "剩", "了", "人",
    # punctuation
    "?", "？", "!", "！", ".", "。", "，", ",", "、",
]


def _extract_destination_hint(normalized: str, date_substring: str | None) -> str | None:
    """Strip date + filler words; remainder is sent to WC `?search=` as-is."""
    text = normalized
    if date_substring:
        text = text.replace(date_substring, " ")
    for tok in _STRIP_TOKENS:
        text = text.replace(tok, " ")
    cleaned = " ".join(text.split())
    return cleaned if cleaned else None


# --- public entry point -----------------------------------------------------

def parse_query(raw_text: str, today: dt.date | None = None) -> ParsedQuery:
    """Main entry. Always returns a ParsedQuery (never raises)."""
    if not raw_text or not raw_text.strip():
        return ParsedQuery(raw_text=raw_text or "", intent=QueryIntent.UNCLEAR,
                           month=None, day=None, destination_hint=None, matched_year=None)

    normalized = _normalize(raw_text)
    month, day, date_substring = _extract_date(normalized)
    destination_hint = _extract_destination_hint(normalized, date_substring)
    matched_year = _infer_year(month, day, today) if (month and day) else None

    lifecycle_hint = _detect_lifecycle_hint(normalized)
    year_qualifier = _detect_year_qualifier(normalized)
    is_aggregate = _is_aggregate_query(normalized)

    extras = {
        "normalized": normalized,
        "date_substring": date_substring,
        "lifecycle_hint": lifecycle_hint,
        "year_qualifier": year_qualifier,
        "is_aggregate": is_aggregate,
    }

    # Type 2 indicator wins — refuse early, do not try to "be helpful".
    if _looks_like_price_edit(normalized):
        return ParsedQuery(
            raw_text=raw_text,
            intent=QueryIntent.PRICE_EDIT_HINT,
            month=month, day=day,
            destination_hint=destination_hint,
            matched_year=matched_year,
            extras=extras,
        )

    # Historical / lifecycle / aggregate query — Type 3/4 lite path.
    if _is_historical_query(normalized, lifecycle_hint, is_aggregate):
        return ParsedQuery(
            raw_text=raw_text,
            intent=QueryIntent.HISTORICAL_LOOKUP,
            month=month, day=day,
            destination_hint=destination_hint,
            matched_year=matched_year,
            extras=extras,
        )

    has_avail_kw = _has_availability_keyword(normalized)
    has_date_and_dest = (month is not None and day is not None and bool(destination_hint))

    if has_avail_kw or has_date_and_dest:
        intent = QueryIntent.AVAILABILITY_CHECK
    else:
        intent = QueryIntent.UNCLEAR

    return ParsedQuery(
        raw_text=raw_text,
        intent=intent,
        month=month, day=day,
        destination_hint=destination_hint,
        matched_year=matched_year,
        extras=extras,
    )
