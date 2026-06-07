"""人名 NER 去識別 —— 第二道關(補 redact.py 漏掉的同行旅客中文姓名)。

背景(見 MAINTENANCE.md §10):redact.py 用「已知顯示名(傳送者名 + 檔名客名)」
逐字遮蔽,主帳號客人名覆蓋良好,但**同行旅客的名字若只出現在文字中**
(例:「跟金華兩人一間」「想跟王金華同房」)會漏 → 結構化正則也攔不到人名。

本檔用本機 gpt-oss:120b 做一道 LLM/NER pass,專抓中文姓名/稱謂,把它換成 [NAME]。

設計鐵則(對齊本專案):
- 純 stdlib(urllib),不引第三方;
- LLM **只做離線處理,不進任何即時控制流**;
- 量太大不可能對每則訊息跑 LLM → 本 pass **只套在 gold 層**(knowledge_units),
  gold 量小、是對外共用的 canonical,值得花一次 LLM 成本把人名洗乾淨;
- 冪等:加 `ner_done boolean default false` 欄位控制,跑過的不重跑;
- 容錯:LLM 失敗一律回原文(去識別寧可少遮一次,也不要因例外把資料弄壞)。

------------------------------------------------------------------
整合說明(未來 label 階段產 gold 時順手呼叫)
------------------------------------------------------------------
最小無破壞做法(不必改 pipeline.py):label 跑完後,定期執行

    ./.venv/bin/python redact_ner.py            # backfill 全部未處理 gold

若要 hook 進 pipeline.label_stage 讓「產 gold 時就洗乾淨」,在 pipeline.py
INSERT knowledge_units **之前**這樣包(對 text / answer 各跑一次):

    import redact_ner as RN
    text,   _ = RN.ner_redact(text)
    if answer:
        answer, _ = RN.ner_redact(answer)

注意:這會讓 label 階段每單元多兩次 LLM 呼叫(較慢);若 label 已用 gpt-oss
標意圖,額外成本可接受。content_hash 仍用洗後文字計算 → 自然冪等。
若選 hook 進 label,INSERT 時把 ner_done 直接設 true,backfill 就不會重做。
"""
from __future__ import annotations

import json
import urllib.request

from config import LABEL_MODEL, OLLAMA_URL, PIPELINE_VERSION
from db import get_conn, start_run, finish_run

_SYSTEM = (
    "你是中文人名去識別器。任務:找出輸入文字中所有指向『真實個人』的人名或稱謂,"
    "包含完整姓名(王金華)、單名/暱稱(金華、阿明)、加稱謂的人名(王先生、陳小姐、林大哥)。\n"
    "規則:\n"
    "1. 只抓人名/人的稱謂,不要抓:公司行號(阿玩旅遊)、地名(韓國、首爾)、"
    "行程名、品牌、貼圖代碼(Brown bow)、已遮蔽標記([NAME]/[PHONE] 等)。\n"
    "2. 純稱呼(您好、客人、大家)不是人名,不要抓。\n"
    "3. 只輸出一個 JSON 物件,格式 {\"names\": [\"王金華\", \"金華\"]},無多餘文字。\n"
    "4. 若沒有人名,輸出 {\"names\": []}。"
)


def _chat(text: str, timeout: float = 60.0) -> str:
    body = json.dumps({
        "model": LABEL_MODEL,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": text}],
        "stream": False, "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def _coerce(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            return json.loads(raw[s:e + 1])
        raise


def _apply_names(text: str, names) -> tuple[str, int]:
    """把模型回的人名清單套到文字上,換成 [NAME]。回 (new_text, 替換數)。"""
    if not isinstance(names, list):
        return text, 0
    cands = sorted(
        {n.strip() for n in names
         if isinstance(n, str) and len(n.strip()) >= 2 and n.strip() in text},
        key=len, reverse=True,  # 長的先換,避免「王金華」被「金華」截斷
    )
    out, count = text, 0
    for name in cands:
        if "[" in name or "]" in name:   # 別把已遮標記當人名
            continue
        occ = out.count(name)
        if occ:
            out = out.replace(name, "[NAME]")
            count += occ
    return out, count


def ner_redact(text: str) -> tuple[str, int]:
    """用 gpt-oss 找人名,換成 [NAME]。回 (new_text, 替換數)。失敗回原文。"""
    if not text or not text.strip():
        return text, 0
    try:
        d = _coerce(_chat(text))
        return _apply_names(text, d.get("names", []))
    except Exception:  # noqa: BLE001 — 去識別容錯:寧可不遮也不破壞資料
        return text, 0


# ---- 批次版:一個 prompt 抓多則的人名,大幅降低呼叫數 -----------------------
_BATCH_SYSTEM = (
    "你是中文人名去識別器。我會給你一個編號清單的文字。對每一則,找出所有指向"
    "『真實個人』的人名或稱謂(完整姓名王金華、單名/暱稱金華阿明、加稱謂王先生陳小姐)。\n"
    "不要抓:公司行號(阿玩旅遊)、地名、行程名、品牌、貼圖代碼、已遮標記[NAME]等;"
    "純稱呼(您好、客人、大家)也不是人名。\n"
    '只輸出一個 JSON 物件 {"results":[{"i":編號,"names":["王金華"]}, ...]},無多餘文字。'
    "每則都要有對應元素,沒人名就 names:[]。"
)


def _chat_batch(listing: str, timeout: float = 120.0) -> str:
    body = json.dumps({
        "model": LABEL_MODEL,
        "messages": [{"role": "system", "content": _BATCH_SYSTEM},
                     {"role": "user", "content": listing}],
        "stream": False, "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def ner_redact_batch(texts: list[str]) -> list[tuple[str, int]]:
    """批次找人名。回跟輸入等長的 [(new_text,count)]。批次失敗退回逐筆(確保不漏遮)。"""
    if not texts:
        return []
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    try:
        d = _coerce(_chat_batch(listing))
        by_i = {int(r["i"]): r.get("names", []) for r in d.get("results", [])
                if isinstance(r, dict) and "i" in r}
        if not by_i:
            raise ValueError("empty results")
        return [_apply_names(t, by_i.get(i, [])) for i, t in enumerate(texts)]
    except Exception:  # noqa: BLE001 — 批次壞掉就逐筆(慢但正確,不漏遮)
        return [ner_redact(t) for t in texts]


# ---------- gold backfill ---------------------------------------------------
def _ensure_column(conn) -> None:
    conn.execute(
        "ALTER TABLE knowledge_units "
        "ADD COLUMN IF NOT EXISTS ner_done boolean NOT NULL DEFAULT false"
    )
    conn.commit()


def backfill_gold(limit: int | None = None) -> dict:
    """掃 knowledge_units(ner_done=false),對 question/answer 各跑 ner_redact,
    遮到人名就 UPDATE 回去;不論有沒有遮都把 ner_done 設 true(冪等)。
    回 {scanned, updated, names_redacted}。"""
    conn = get_conn()
    _ensure_column(conn)
    run = start_run(conn, "ner", PIPELINE_VERSION)
    rows = conn.execute(
        "SELECT id, question, answer FROM knowledge_units "
        "WHERE ner_done = false ORDER BY id " + ("LIMIT %s" if limit else ""),
        ((limit,) if limit else ()),
    ).fetchall()

    scanned = updated = total_names = 0
    CHUNK = 10  # 每批 10 個單元(≈20 段文字)一次 LLM 呼叫
    for b in range(0, len(rows), CHUNK):
        chunk = rows[b:b + CHUNK]
        # 攤平成文字清單(記住每段屬於哪個 unit 的 q 還是 a)
        texts, refs = [], []
        for kid, question, answer in chunk:
            if question:
                refs.append((kid, "q")); texts.append(question)
            if answer:
                refs.append((kid, "a")); texts.append(answer)
        results = ner_redact_batch(texts)
        # 收回每個 unit 的新 q/a
        agg = {kid: {"q": q, "a": a, "n": 0} for kid, q, a in chunk}
        for (kid, field), (new_text, cnt) in zip(refs, results):
            agg[kid][field] = new_text
            agg[kid]["n"] += cnt
        for kid, question, answer in chunk:
            scanned += 1
            a = agg[kid]
            try:
                if a["n"] > 0:
                    conn.execute(
                        "UPDATE knowledge_units SET question=%s, answer=%s, "
                        "ner_done=true, updated_at=now() WHERE id=%s",
                        (a["q"], a["a"], kid))
                    updated += 1
                    total_names += a["n"]
                else:
                    conn.execute(
                        "UPDATE knowledge_units SET ner_done=true WHERE id=%s", (kid,))
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                print(f"  ner 失敗 id={kid}: {type(e).__name__}: {e}")
                continue
        conn.commit()

    finish_run(conn, run, updated,
               notes=f"scanned={scanned} names_redacted={total_names}")
    conn.close()
    return {"scanned": scanned, "updated": updated, "names_redacted": total_names}


if __name__ == "__main__":
    import sys
    lim = None
    if len(sys.argv) > 1:
        try:
            lim = int(sys.argv[1])
        except ValueError:
            pass
    res = backfill_gold(limit=lim)
    print(f"NER backfill 完成:掃 {res['scanned']} 筆,"
          f"更新 {res['updated']} 筆,共遮 {res['names_redacted']} 個人名。")
