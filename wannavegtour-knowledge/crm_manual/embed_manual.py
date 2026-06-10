#!/usr/bin/env python3
"""把 crm_assistant_kb 的 approved 條目嵌入 Qdrant(qwen3-embedding:8b, 4096 維)。
統一資料來源:同一個 Qdrant、同一台本地 Ollama。只嵌 status=approved。冪等:整個 collection 重建。
查詢端用法見 reference_local_models:要帶 Instruct 前綴。"""
import json, subprocess, urllib.request

OLLAMA = "http://127.0.0.1:11434/api/embed"
QDRANT = "http://127.0.0.1:6333"
COLL = "crm_manual"
MODEL = "qwen3-embedding:8b"
DIM = 4096

def embed(texts):
    req = urllib.request.Request(OLLAMA, data=json.dumps({"model": MODEL, "input": texts}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["embeddings"]

def q(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(QDRANT + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

rows = subprocess.run(["docker","exec","wannaveg-dev-pg","psql","-U","wv","-d","crm_assistant_kb","-tA","-R","\x1e","-F","\x1f","-c",
    "select entry_code, domain, title, array_to_string(question_forms,' / '), answer, coalesce(ui_path,'') from manual_entries where status='approved' order by entry_code"],
    capture_output=True).stdout.decode()
items = [r.split("\x1f") for r in rows.split("\x1e") if r.strip()]
print(f"approved 條目: {len(items)}")

# 文件端嵌入文本 = 標題+問法+答案(原文,不加 Instruct 前綴)
docs = [f"{code} {title}\n問法:{qf}\n{ans}" for code, dom, title, qf, ans, ui in items]
vecs = []
for i in range(0, len(docs), 16):
    vecs.extend(embed(docs[i:i+16]))
    print(f"  embedded {min(i+16,len(docs))}/{len(docs)}")

try: q("DELETE", f"/collections/{COLL}")
except Exception: pass
q("PUT", f"/collections/{COLL}", {"vectors": {"size": DIM, "distance": "Cosine"}})
points = [{"id": i+1, "vector": v, "payload": {
    "entry_code": items[i][0], "domain": items[i][1], "title": items[i][2],
    "answer": items[i][4], "ui_path": items[i][5]}} for i, v in enumerate(vecs)]
q("PUT", f"/collections/{COLL}/points", {"points": points})
info = q("GET", f"/collections/{COLL}")
print(f"Qdrant {COLL}: {info['result']['points_count']} points, dim={DIM}")
