"""Interactive REPL for manual testing.

Usage:
    python3 -m wannavegtour.cli

Type a question (LINE-style) and see the formatted answer.
Type "exit" / "quit" or press Ctrl-D to leave.
Add "?" prefix to also show the parser breakdown for debugging.
"""

from __future__ import annotations

import sys

from . import (
    AvailabilityChecker,
    HistoricalLookup,
    WCClient,
    format_historical,
    format_response,
    load_config,
    parse_query,
)
from .config import CredentialError
from .query_parser import QueryIntent


PROMPT = "OP 群訊息> "
HELP = """指令：
  <任何中文訊息>     送進 parser + checker，看 LINE 風格回覆
  ?<訊息>          多印一份 parser 內部資訊 (debug)
  help             顯示這個說明
  exit / quit      離開
"""


def main() -> int:
    try:
        config = load_config()
    except CredentialError as e:
        print(f"[fatal] 找不到 / 讀不到 credentials: {e}", file=sys.stderr)
        print(
            f"建議：到 WP 後台 WooCommerce → 設定 → 進階 → REST API 建立 key，"
            f"填進 ~/.hermes/credentials/wannavegtour/wc-api.json 後再跑。",
            file=sys.stderr,
        )
        return 1

    client = WCClient(config)
    checker = AvailabilityChecker(client)
    history = HistoricalLookup(client)

    print(f"已連線：{config.api_root}  (permissions: {config.permissions})")
    print(HELP)

    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("exit", "quit"):
            return 0
        if line == "help":
            print(HELP)
            continue

        debug = line.startswith("?")
        if debug:
            line = line[1:].strip()
            if not line:
                continue

        parsed = parse_query(line)
        if debug:
            print(
                f"  [parsed] intent={parsed.intent.value} "
                f"month={parsed.month} day={parsed.day} year={parsed.matched_year} "
                f"dest={parsed.destination_hint!r}"
            )
            print(f"  [extras] {parsed.extras}")

        # Route based on intent.
        if parsed.intent == QueryIntent.HISTORICAL_LOOKUP:
            h = history.lookup(parsed)
            if debug:
                print(f"  [result] historical kind={h.kind.value} products={len(h.products)}")
            print()
            print(format_historical(h))
            print()
        else:
            result = checker.check(parsed)
            if debug:
                print(f"  [result] availability kind={result.kind.value} products={len(result.products)}")
            print()
            print(format_response(result))
            print()


if __name__ == "__main__":
    sys.exit(main())
