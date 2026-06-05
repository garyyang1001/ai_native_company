"""全面去識別(PII redaction)—— silver/gold 一律經過這裡,bronze 不動。

策略:結構化 PII 用正則可靠攔截(電話/身分證/護照/信用卡/email);
姓名屬自由文字,難以純規則完全攔,故額外吃「已知顯示名」清單(從 CSV 的
傳送者名稱 + 檔名客名抽出)逐字遮蔽。LLM/NER 加強留作後續強化(見維護文件)。
"""
from __future__ import annotations

import re

_PATTERNS = [
    # 台灣手機 / 市話:0912-345-678 / 0912345678 / 09 1234 5678 / (02)1234-5678
    (re.compile(r"(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,4}(?!\d)"), "[PHONE]"),
    # 台灣身分證:A123456789
    (re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![A-Za-z0-9])"), "[ID]"),
    # 護照:多為 8-9 碼英數
    (re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{8,9}(?![A-Za-z0-9])"), "[PASSPORT]"),
    # 信用卡:13-16 連續數字(可帶分隔)
    (re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)"), "[CARD]"),
    # email
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]


def redact(text: str, known_names: set[str] | None = None) -> tuple[str, int]:
    """回 (去識別後文字, 遮蔽處數)。"""
    if not text:
        return text, 0
    count = 0
    out = text

    # 1) 先遮已知人名(長度 >=2 才遮,避免單字誤殺)
    if known_names:
        for name in sorted((n for n in known_names if n and len(n) >= 2), key=len, reverse=True):
            if name in out:
                count += out.count(name)
                out = out.replace(name, "[NAME]")

    # 2) 結構化 PII
    for pat, repl in _PATTERNS:
        out, n = pat.subn(repl, out)
        count += n

    return out, count
