"""ElevenLabs 知識庫匯出器 —— 把 gold(knowledge_units, status='active')
依「行程 / 主題」聚合成乾淨 Markdown,寫到 out/elevenlabs/,並可選擇上傳到
ElevenLabs Knowledge Base。

設計遵專案鐵則:
  - 純 stdlib(urllib),不引第三方 HTTP 套件;
  - 金鑰只從環境變數 ELEVENLABS_API_KEY 讀,絕不寫死;沒設就 dry-run(只寫檔);
  - 只讀 gold(canonical 唯一真相),gold 一行不用改即可換下游;
  - LLM 不進控制流(此匯出器根本不碰 LLM,純結構化轉換);
  - PII 已在 silver/gold 去識別過,這裡只搬運不還原。

用法:
  ./.venv/bin/python exporters/export_elevenlabs.py            # 預設:寫檔 + (有金鑰才)上傳
  ./.venv/bin/python exporters/export_elevenlabs.py --dry-run  # 強制只寫檔,絕不上傳
  ./.venv/bin/python exporters/export_elevenlabs.py --min-quality 0.7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

# 讓本檔放在 exporters/ 子目錄下也能 import 專案根的 config/db
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import PIPELINE_VERSION  # noqa: E402
from db import get_conn, start_run, finish_run  # noqa: E402

OUT_DIR = _ROOT / "out" / "elevenlabs"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/convai/knowledge-base/text"

# gold intent → 對外讀者看得懂的中文標題
_INTENT_ZH = {
    "availability_check": "名額與成團",
    "historical_lookup": "歷史紀錄查詢",
    "price_inquiry": "費用與付款",
    "itinerary_detail": "行程細節",
    "booking_action": "報名與訂位",
    "complaint": "問題反映",
    "unclear": "其他詢問",
    "noise": "雜訊",
}
# intent 在文件內的呈現順序(常見/重要的在前)
_INTENT_ORDER = [
    "availability_check", "price_inquiry", "itinerary_detail",
    "booking_action", "historical_lookup", "complaint", "unclear",
]


def _slugify(text: str) -> str:
    """檔名安全化:保留中英數,其餘換底線。"""
    s = re.sub(r"[^\w一-鿿]+", "_", text.strip())
    s = s.strip("_")
    return s or "untitled"


def _doc_key(dest: str | None, date: str | None) -> tuple[str, str]:
    """回 (聚合鍵, 人看的標題)。有行程 → 依行程(+日期);沒有 → 歸『一般詢問』。"""
    if dest:
        title = f"{dest}行程" + (f"({date})" if date else "")
        key = _slugify(dest + ("_" + date.replace("/", "-") if date else ""))
        return key, title
    return "general", "一般詢問(未指定行程)"


def fetch_units(min_quality: float = 0.0) -> list[dict]:
    """讀 gold(status='active'),回 list[dict]。只讀 canonical,不碰 PII 源。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, question, answer, intent, tour_destination, tour_date, quality "
            "FROM knowledge_units "
            "WHERE status='active' AND quality >= %s "
            "ORDER BY tour_destination NULLS LAST, tour_date NULLS LAST, intent, id",
            (min_quality,),
        ).fetchall()
    finally:
        conn.close()
    cols = ("id", "question", "answer", "intent", "tour_destination", "tour_date", "quality")
    return [dict(zip(cols, r)) for r in rows]


def _clean_cell(text: str | None) -> str:
    """把多行/多空白壓成單行,給 Markdown 條目用。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def group_units(units: list[dict]) -> "OrderedDict[str, dict]":
    """依行程/主題聚合。回 {key: {title, intents: {intent: [unit...]}}}。"""
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for u in units:
        key, title = _doc_key(u["tour_destination"], u["tour_date"])
        g = groups.setdefault(key, {"title": title, "intents": {}})
        g["intents"].setdefault(u["intent"], []).append(u)
    return groups


def render_markdown(title: str, intents: dict[str, list[dict]]) -> str:
    """把一個聚合渲染成乾淨 Markdown(問答整理)。"""
    lines: list[str] = [f"# {title}", ""]
    lines.append("> 阿玩旅遊客服問答整理(已去識別,自動由知識庫匯出)。")
    lines.append("")
    ordered = [i for i in _INTENT_ORDER if i in intents]
    ordered += [i for i in intents if i not in _INTENT_ORDER]  # 兜底未列入順序的
    for intent in ordered:
        items = [u for u in intents[intent] if _clean_cell(u["question"])]
        if not items:
            continue
        lines.append(f"## {_INTENT_ZH.get(intent, intent)}")
        lines.append("")
        for u in items:
            q = _clean_cell(u["question"])
            a = _clean_cell(u["answer"])
            lines.append(f"- 問:{q}")
            if a:
                lines.append(f"  答:{a}")
            else:
                lines.append("  答:(尚無客服回覆紀錄)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_docs(min_quality: float = 0.0) -> list[Path]:
    """讀 gold → 聚合 → 寫 out/elevenlabs/*.md。回寫出的檔路徑清單。"""
    units = fetch_units(min_quality)
    groups = group_units(units)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key, g in groups.items():
        md = render_markdown(g["title"], g["intents"])
        path = OUT_DIR / f"{key}.md"
        path.write_text(md, encoding="utf-8")
        written.append(path)
    return written


def upload(md_path: str | Path) -> dict | None:
    """把一個 md 檔上傳到 ElevenLabs Knowledge Base。

    POST {ELEVENLABS_URL},header xi-api-key 從環境變數 ELEVENLABS_API_KEY 讀。
    沒設金鑰 → 回 None(dry-run,只印提示,不送任何請求)。
    成功 → 回 API JSON 回應。純 stdlib urllib。
    """
    path = Path(md_path)
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print(f"  [dry-run] 未設 ELEVENLABS_API_KEY,跳過上傳:{path.name}")
        return None

    text = path.read_text(encoding="utf-8")
    body = json.dumps({"text": text, "name": path.stem}).encode("utf-8")
    req = urllib.request.Request(
        ELEVENLABS_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        print(f"  [uploaded] {path.name} → id={resp.get('id', '?')}")
        return resp
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"  [upload 失敗] {path.name}: HTTP {e.code} {detail}")
        return None
    except urllib.error.URLError as e:
        print(f"  [upload 失敗] {path.name}: {e.reason}")
        return None


def export(min_quality: float = 0.0, dry_run: bool = False) -> dict:
    """主流程:寫檔(永遠) + 上傳(有金鑰且非 --dry-run)。記一筆 pipeline_run。"""
    conn = get_conn()
    run = start_run(conn, "export", PIPELINE_VERSION)
    conn.close()

    written = write_docs(min_quality)
    has_key = bool(os.environ.get("ELEVENLABS_API_KEY"))
    will_upload = has_key and not dry_run

    print(f"寫出 {len(written)} 個 Markdown 檔到 {OUT_DIR}")
    for p in written:
        print(f"  - {p.name}")

    uploaded = 0
    if will_upload:
        print("開始上傳到 ElevenLabs Knowledge Base ...")
        for p in written:
            if upload(p) is not None:
                uploaded += 1
    else:
        reason = "--dry-run" if dry_run else "未設 ELEVENLABS_API_KEY"
        print(f"[dry-run] 不上傳({reason}),僅寫檔完成。")

    notes = f"docs={len(written)} uploaded={uploaded} dry_run={not will_upload} min_quality={min_quality}"
    conn = get_conn()
    finish_run(conn, run, len(written), notes=notes)
    conn.close()
    return {"docs": len(written), "uploaded": uploaded, "dry_run": not will_upload,
            "out_dir": str(OUT_DIR), "files": [str(p) for p in written]}


def main() -> None:
    ap = argparse.ArgumentParser(description="把 gold 匯出成 ElevenLabs 知識庫 Markdown(+可選上傳)")
    ap.add_argument("--dry-run", action="store_true", help="強制只寫檔,絕不上傳")
    ap.add_argument("--min-quality", type=float, default=0.0, help="只匯出 quality >= 此值的單元")
    args = ap.parse_args()
    result = export(min_quality=args.min_quality, dry_run=args.dry_run)
    print("\n結果:" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
