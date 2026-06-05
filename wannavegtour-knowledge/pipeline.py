"""三階段管線:bronze ingest → silver clean → gold label。
全部冪等、帶 pipeline 版本,可重跑/重洗。"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone, timedelta

from config import PIPELINE_VERSION, ZIP_PATH
import clean as C
import redact as R
import labeler as L
from db import get_conn, start_run, finish_run

_TZ = timezone(timedelta(hours=9))  # LINE OA 匯出時區 +09:00

# 行程目的地關鍵字(gold tour_destination 用;best-effort,非 PII)
_DEST = ["日本", "韓國", "江南", "峇里島", "東北", "不丹", "北疆", "峴港", "大阪",
         "東京", "北海道", "立山黑部", "清邁", "越南", "九州", "關西", "沖繩",
         "泰國", "新加坡", "馬來西亞", "歐洲", "土耳其", "埃及", "杜拜", "中歐",
         "義大利", "西班牙", "法國", "美國", "加拿大", "紐西蘭", "澳洲", "印度"]


def _sha(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def _parse_filename(name: str) -> tuple[str, str | None, str | None]:
    """回 (name_guess 給去識別用, tour_date, tour_destination)。"""
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    body = re.sub(r"^\d+_", "", base)           # 去掉前面索引
    body = re.sub(r"^\d{8}_\d{8}_", "", body)   # 去掉日期區間前綴(若有)
    name_guess = body.split(" ")[0].split("　")[0] if body else ""
    date = None
    m = re.search(r"(\d{1,2})[_/](\d{1,2})", body)
    if m:
        date = f"{int(m.group(1))}/{int(m.group(2))}"
    dest = next((d for d in _DEST if d in body), None)
    return name_guess.strip(), date, dest


# ---------- bronze ----------------------------------------------------------
def ingest(limit: int | None = None) -> int:
    conn = get_conn()
    run = start_run(conn, "ingest", PIPELINE_VERSION)
    z = zipfile.ZipFile(ZIP_PATH)
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if limit:
        names = names[:limit]
    new_files = 0
    for n in names:
        raw = z.read(n)
        fsha = _sha(raw)
        exists = conn.execute("SELECT id FROM source_files WHERE file_sha256=%s", (fsha,)).fetchone()
        if exists:
            continue
        txt = raw.decode("utf-8-sig", "replace")
        rows = list(csv.reader(io.StringIO(txt)))
        meta = {r[0]: r[1] for r in rows if len(r) >= 2 and r[0] in ("帳號名稱", "時區", "下載時間")}
        hi = next((i for i, r in enumerate(rows) if r and r[0] == "傳送者類型"), None)
        data = rows[hi + 1:] if hi is not None else []
        name_guess, _, _ = _parse_filename(n)
        try:
            fid = conn.execute(
                "INSERT INTO source_files (filename, file_sha256, account_name, timezone, "
                "download_time, conv_external_key, msg_count) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (n, fsha, meta.get("帳號名稱"), meta.get("時區"), meta.get("下載時間"),
                 re.sub(r"^\d+_", "", n.rsplit('.', 1)[0]), len(data)),
            ).fetchone()[0]
            seq = 0
            for r in data:
                if len(r) < 5:
                    continue
                role, sname, sdate, stime, content = r[0], r[1], r[2], r[3], r[4]
                ts = None
                try:
                    ts = datetime.strptime(f"{sdate} {stime}", "%Y/%m/%d %H:%M:%S").replace(tzinfo=_TZ)
                except Exception:
                    pass
                conn.execute(
                    "INSERT INTO raw_turns (source_file_id, seq, role, sender_name, sent_date, "
                    "sent_time, sent_ts, raw_text, content_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (fid, seq, role, sname, sdate, stime, ts, content, _sha(content)),
                )
                seq += 1
            conn.commit()
            new_files += 1
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            print(f"  ingest 失敗 {n}: {type(e).__name__}: {e}")
    finish_run(conn, run, new_files, notes=f"{len(names)} scanned")
    conn.close()
    return new_files


# ---------- silver ----------------------------------------------------------
def clean_stage(limit: int | None = None) -> int:
    conn = get_conn()
    run = start_run(conn, "clean", PIPELINE_VERSION)
    # 每個 file 蒐集已知人名(去識別用):傳送者名稱(User) + 檔名客名
    files = conn.execute(
        "SELECT sf.id, sf.filename FROM source_files sf "
        "WHERE EXISTS (SELECT 1 FROM raw_turns rt WHERE rt.source_file_id=sf.id "
        "  AND NOT EXISTS (SELECT 1 FROM clean_turns ct JOIN raw_turns r2 ON ct.raw_turn_id=r2.id "
        "                  WHERE r2.id=rt.id AND ct.pipeline_version=%s)) "
        + ("LIMIT %s" if limit else ""),
        ((PIPELINE_VERSION, limit) if limit else (PIPELINE_VERSION,)),
    ).fetchall()
    done = 0
    for fid, fname in files:
        name_guess, _, _ = _parse_filename(fname)
        # 去識別已知人名 = 檔名客名 + 全對話的傳送者名(可靠來源)
        snames = conn.execute(
            "SELECT DISTINCT sender_name FROM raw_turns WHERE source_file_id=%s "
            "AND role='User' AND sender_name IS NOT NULL AND sender_name<>''", (fid,)).fetchall()
        names = ({name_guess} if name_guess else set()) | {s[0] for s in snames}
        turns = conn.execute(
            "SELECT rt.id, rt.role, rt.raw_text FROM raw_turns rt "
            "WHERE rt.source_file_id=%s ORDER BY rt.seq", (fid,)).fetchall()
        for rid, role, raw_text in turns:
            already = conn.execute(
                "SELECT 1 FROM clean_turns WHERE raw_turn_id=%s AND pipeline_version=%s",
                (rid, PIPELINE_VERSION)).fetchone()
            if already:
                continue
            norm_role = "customer" if role == "User" else "agent"
            noise = C.is_noise(raw_text)
            clean_text, rcount = R.redact(C.normalize(raw_text), known_names=names)
            conn.execute(
                "INSERT INTO clean_turns (raw_turn_id, pipeline_version, role, clean_text, "
                "is_noise, redaction_count) VALUES (%s,%s,%s,%s,%s,%s)",
                (rid, PIPELINE_VERSION, norm_role, clean_text, noise, rcount))
            done += 1
        conn.commit()
    finish_run(conn, run, done)
    conn.close()
    return done


# ---------- gold ------------------------------------------------------------
def label_stage(limit_files: int | None = None) -> int:
    conn = get_conn()
    run = start_run(conn, "label", PIPELINE_VERSION)
    # 可續跑:跳過已經有 knowledge_units 的 source_file(中斷重啟不重做)
    files = conn.execute(
        "SELECT DISTINCT rt.source_file_id, sf.filename FROM clean_turns ct "
        "JOIN raw_turns rt ON ct.raw_turn_id=rt.id JOIN source_files sf ON sf.id=rt.source_file_id "
        "WHERE ct.pipeline_version=%s "
        "AND NOT EXISTS (SELECT 1 FROM knowledge_units ku WHERE ku.source_file_id=rt.source_file_id) "
        "ORDER BY rt.source_file_id "
        + ("LIMIT %s" if limit_files else ""),
        ((PIPELINE_VERSION, limit_files) if limit_files else (PIPELINE_VERSION,)),
    ).fetchall()
    units = 0
    for fid, fname in files:
        _, tdate, tdest = _parse_filename(fname)
        turns = conn.execute(
            "SELECT ct.id, ct.role, ct.clean_text, ct.is_noise, rt.seq FROM clean_turns ct "
            "JOIN raw_turns rt ON ct.raw_turn_id=rt.id "
            "WHERE rt.source_file_id=%s AND ct.pipeline_version=%s ORDER BY rt.seq",
            (fid, PIPELINE_VERSION)).fetchall()
        # 配對:每個 customer 非 noise turn → 之後第一個 agent 非 noise turn
        for i, (cid, role, text, noise, seq) in enumerate(turns):
            if role != "customer" or noise or not text:
                continue
            answer, ans_id = None, None
            for cid2, role2, text2, noise2, _s2 in turns[i + 1:]:
                if role2 == "agent" and not noise2 and text2:
                    answer, ans_id = text2, cid2
                    break
                if role2 == "customer" and not noise2:
                    break  # 客人連發,先不跨過去
            lab = L.label(text)
            if lab["is_noise"]:
                continue
            chash = _sha(f"{text}||{answer or ''}||{lab['intent']}")
            quality = round(min(1.0, (lab["confidence"] * 0.6) +
                                (0.4 if answer and len(answer) > 4 else 0.0)), 3)
            sids = [cid] + ([ans_id] if ans_id else [])
            try:
                cur = conn.execute(
                    "INSERT INTO knowledge_units (source_file_id, question, answer, intent, "
                    "confidence, parser_missed, tour_destination, tour_date, quality, "
                    "source_turn_ids, pipeline_version, label_model, content_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (content_hash) DO NOTHING",
                    (fid, text, answer, lab["intent"], lab["confidence"], lab["parser_missed"],
                     tdest, tdate, quality, sids, PIPELINE_VERSION, lab["model"], chash))
                if cur.rowcount and cur.rowcount > 0:
                    units += 1
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                continue
        conn.commit()
    finish_run(conn, run, units)
    conn.close()
    return units
