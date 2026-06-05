"""SFT 匯出器 —— gold(knowledge_units)→ 微調用對話 JSONL。

讀 canonical gold,做品質過濾,輸出 OpenAI/通用對話格式的 JSONL,
每行一筆 {"messages":[system, user, assistant]}。離線匯出,不進控制流。

用法:
    ./.venv/bin/python exporters/export_sft.py
    ./.venv/bin/python exporters/export_sft.py --min-quality 0.6
    ./.venv/bin/python exporters/export_sft.py --out /tmp/foo.jsonl

設計沿用本專案慣例:
- 純 stdlib(json / argparse / pathlib);
- DB 走 db.get_conn()(憑證 config.load_db_config(),不寫死);
- 只讀 gold,bronze PII 永不碰;
- 匯出留帳:寫一筆 pipeline_runs(stage='export')。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允許從 exporters/ 子目錄直接執行也能 import 專案根模組
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PIPELINE_VERSION  # noqa: E402
from db import get_conn, start_run, finish_run  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _ROOT / "out" / "sft_dataset.jsonl"

# 客服自動回覆樣板特徵字串:命中任一即視為樣板,跳過(非真人回答,對微調有害)
_AUTOREPLY_MARKERS = ("下班時間", "無法即時回覆")

# 預設品質下限。gold.quality 為 0~1;空答 / 弱配對通常落在 ~0.5 以下。
_DEFAULT_MIN_QUALITY = 0.5

_SYSTEM_PROMPT = (
    "你是阿玩旅遊客服。以親切、專業、簡潔的繁體中文回覆客人,"
    "依旅遊團報名、成團狀態、行程細節、費用與付款等情境提供協助。"
)


def _is_autoreply(text: str) -> bool:
    return any(m in text for m in _AUTOREPLY_MARKERS)


def export(out_path: Path, min_quality: float) -> dict:
    """讀 gold → 過濾 → 寫 JSONL。回傳統計 dict。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    run = start_run(conn, "export", PIPELINE_VERSION)

    rows = conn.execute(
        "SELECT id, question, answer, quality FROM knowledge_units "
        "WHERE status = 'active' AND answer IS NOT NULL AND btrim(answer) <> '' "
        "ORDER BY id"
    ).fetchall()

    stats = {
        "read": len(rows),
        "written": 0,
        "skip_empty_question": 0,
        "skip_empty_answer": 0,
        "skip_autoreply": 0,
        "skip_low_quality": 0,
    }

    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for _id, question, answer, quality in rows:
            # 答案空(SQL 已濾大部分,這裡防 NULL/純空白漏網)
            if not answer or not answer.strip():
                stats["skip_empty_answer"] += 1
                continue
            # 問題空 → 無法構成 user 輪
            if not question or not question.strip():
                stats["skip_empty_question"] += 1
                continue
            # 客服自動回覆樣板 → 跳過
            if _is_autoreply(answer):
                stats["skip_autoreply"] += 1
                continue
            # 品質太低 → 跳過
            if (quality or 0.0) < min_quality:
                stats["skip_low_quality"] += 1
                continue

            record = {
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": question.strip()},
                    {"role": "assistant", "content": answer.strip()},
                ]
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    stats["written"] = written
    stats["skipped"] = stats["read"] - written

    notes = (
        f"out={out_path} min_quality={min_quality} "
        f"written={written} skipped={stats['skipped']} "
        f"(empty_q={stats['skip_empty_question']} "
        f"empty_a={stats['skip_empty_answer']} "
        f"autoreply={stats['skip_autoreply']} "
        f"low_quality={stats['skip_low_quality']})"
    )
    finish_run(conn, run, written, notes=notes)
    conn.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="把 gold 匯出成 SFT 對話 JSONL")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="輸出 JSONL 路徑")
    ap.add_argument("--min-quality", type=float, default=_DEFAULT_MIN_QUALITY,
                    help=f"品質下限 0~1(預設 {_DEFAULT_MIN_QUALITY})")
    args = ap.parse_args()

    stats = export(Path(args.out), args.min_quality)

    print(f"輸出: {args.out}")
    print(f"讀取 gold(active+有答): {stats['read']} 筆")
    print(f"寫入: {stats['written']} 筆")
    print(f"過濾掉: {stats['skipped']} 筆")
    print(f"  - 問題為空: {stats['skip_empty_question']}")
    print(f"  - 答案為空: {stats['skip_empty_answer']}")
    print(f"  - 自動回覆樣板: {stats['skip_autoreply']}")
    print(f"  - 品質過低(<{args.min_quality}): {stats['skip_low_quality']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
