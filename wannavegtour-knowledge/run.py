#!/usr/bin/env python3
"""CLI:跑 bronze/silver/gold 三階段。

  python run.py ingest [--limit N]      # 匯入 N 個對話檔到 bronze
  python run.py clean  [--limit N]      # 清洗+去識別 → silver
  python run.py label  [--limit N]      # 配問答+標意圖 → gold
  python run.py all    [--limit N]      # 三階段依序
  python run.py stats                   # 看現況

冪等:重跑只處理還沒處理的。改規則→ config.PIPELINE_VERSION +1 即可重洗。
"""
from __future__ import annotations

import argparse

import pipeline as P
from db import get_conn


def stats() -> None:
    conn = get_conn()
    q = lambda s: conn.execute(s).fetchone()[0]
    print("=== wannavegtour_knowledge 現況 ===")
    print(f"  bronze source_files : {q('SELECT count(*) FROM source_files')}")
    print(f"  bronze raw_turns    : {q('SELECT count(*) FROM raw_turns')}")
    print(f"  silver clean_turns  : {q('SELECT count(*) FROM clean_turns')}")
    print(f"    其中 noise        : {q('SELECT count(*) FROM clean_turns WHERE is_noise')}")
    print(f"  gold knowledge_units: {q('SELECT count(*) FROM knowledge_units')}")
    print(f"    parser 漏接       : {q('SELECT count(*) FROM knowledge_units WHERE parser_missed')}")
    rows = conn.execute("SELECT intent, count(*) FROM knowledge_units GROUP BY intent ORDER BY 2 DESC").fetchall()
    if rows:
        print("  意圖分布:", {r[0]: r[1] for r in rows})
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ingest", "clean", "label", "all", "stats"])
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    if a.cmd == "stats":
        stats(); return
    if a.cmd in ("ingest", "all"):
        print(f"[ingest] 新匯入 {P.ingest(a.limit)} 個對話檔")
    if a.cmd in ("clean", "all"):
        print(f"[clean]  清洗 {P.clean_stage(a.limit)} 則訊息")
    if a.cmd in ("label", "all"):
        print(f"[label]  產生 {P.label_stage(a.limit)} 個知識單元")
    stats()


if __name__ == "__main__":
    main()
