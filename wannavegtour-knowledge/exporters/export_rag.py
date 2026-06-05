#!/usr/bin/env python3
"""RAG 匯出器 —— gold knowledge_units → bge-m3 向量 → Qdrant 向量庫。

canonical(gold)是唯一真相,這裡只「讀 → 嵌入 → 存向量庫」,不改 gold 一行。
換掉下游向量庫只換這支匯出器即可(見 MAINTENANCE.md §7)。

慣例:
  - 嵌入走本機 Ollama /api/embed(純 stdlib urllib,離線處理不進控制流)。
  - DB 連線一律 db.get_conn()(憑證在 ~/.hermes/credentials,勿寫死)。
  - 每次匯出在 pipeline_runs 留帳(stage='export')。
  - 冪等:point id = knowledge_units.id(unit_id),重跑覆寫不長重複。

用法:
  python exporters/export_rag.py export           # 匯出全部 active gold
  python exporters/export_rag.py search "問句"     # 示範檢索
  python exporters/export_rag.py search "問句" 3   # 取 top-3
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 讓 `python exporters/export_rag.py` 能 import 專案根的 config/db
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PIPELINE_VERSION  # noqa: E402
from db import get_conn, start_run, finish_run  # noqa: E402

# ---- 設定(嵌入 + 向量庫)-------------------------------------------------
EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"
EMBED_DIM = 1024
QDRANT_URL = "http://localhost:6333"
COLLECTION = "wannavegtour_knowledge"


# ---- 嵌入(本機 Ollama,stdlib)------------------------------------------
def embed(texts: list[str], timeout: float = 120.0) -> list[list[float]]:
    """bge-m3 批次嵌入,回 list[向量(1024 維)]。"""
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        EMBED_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    embs = d.get("embeddings") or ([d["embedding"]] if "embedding" in d else [])
    if not embs:
        raise RuntimeError(f"嵌入回應無向量:{d}")
    return embs


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


# ---- 檢索文字組裝 ---------------------------------------------------------
def _retrieval_text(question: str, answer: str | None, intent: str,
                    tour_destination: str | None, tour_date: str | None) -> str:
    """把一個知識單元組成一段適合檢索的文字(問+答+意圖+行程)。"""
    parts = [f"問題:{question}"]
    if answer:
        parts.append(f"回答:{answer}")
    parts.append(f"意圖:{intent}")
    tour = " ".join(p for p in (tour_destination, tour_date) if p)
    if tour:
        parts.append(f"行程:{tour}")
    return "\n".join(parts)


# ---- Qdrant client(lazy)-------------------------------------------------
def _client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL)


def _ensure_collection(client) -> None:
    from qdrant_client.models import Distance, VectorParams
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )


# ---- 匯出(gold → 向量庫)-------------------------------------------------
def export(batch: int = 32) -> int:
    """讀 active gold → 嵌入 → upsert 進 Qdrant。回 upsert 筆數。冪等(unit_id 當 point id)。"""
    from qdrant_client.models import PointStruct

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, question, answer, intent, tour_destination, tour_date, quality "
        "FROM knowledge_units WHERE status='active' ORDER BY id"
    ).fetchall()
    run = start_run(conn, "export", PIPELINE_VERSION, input_count=len(rows))

    client = _client()
    _ensure_collection(client)

    done = 0
    try:
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            texts = [_retrieval_text(r[1], r[2], r[3], r[4], r[5]) for r in chunk]
            vecs = embed(texts)
            points = []
            for r, v in zip(chunk, vecs):
                uid, question, answer, intent, dest, tdate, quality = r
                points.append(PointStruct(
                    id=int(uid),            # 冪等:unit_id 當 point id
                    vector=v,
                    payload={
                        "unit_id": int(uid),
                        "question": question,
                        "answer": answer,
                        "intent": intent,
                        "tour_destination": dest,
                        "tour_date": tdate,
                        "quality": float(quality),
                    },
                ))
            client.upsert(collection_name=COLLECTION, points=points)
            done += len(points)
        finish_run(conn, run, done, notes=f"{COLLECTION} @ {QDRANT_URL}")
    except Exception as e:  # noqa: BLE001
        finish_run(conn, run, done, status="failed", notes=f"{type(e).__name__}: {e}")
        conn.close()
        raise
    conn.close()
    return done


# ---- 檢索示範 -------------------------------------------------------------
def search(query: str, k: int = 5) -> list[dict]:
    """嵌入 query → Qdrant 取 top-k → 回 [{score, ...payload}]。"""
    qv = embed_one(query)
    client = _client()
    hits = client.query_points(
        collection_name=COLLECTION, query=qv, limit=k, with_payload=True,
    ).points
    out = []
    for h in hits:
        item = {"score": round(h.score, 4)}
        item.update(h.payload or {})
        out.append(item)
    return out


# ---- CLI ------------------------------------------------------------------
def _main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("export", "search"):
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "export":
        n = export()
        print(f"[export] upsert {n} 個知識單元到 Qdrant collection '{COLLECTION}'")
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("用法:search \"問句\" [k]")
            sys.exit(1)
        query = sys.argv[2]
        k = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        res = search(query, k)
        print(f"[search] query={query!r} top-{k}:")
        for i, r in enumerate(res, 1):
            print(f"  {i}. score={r['score']} intent={r.get('intent')} "
                  f"tour={r.get('tour_destination')}/{r.get('tour_date')}")
            print(f"     Q: {r.get('question')}")
            ans = r.get("answer")
            if ans:
                print(f"     A: {ans[:120]}")


if __name__ == "__main__":
    _main()
