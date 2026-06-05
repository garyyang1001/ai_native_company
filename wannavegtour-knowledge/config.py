"""設定 —— 憑證從 ~/.hermes/credentials 載,絕不寫死在程式或專案內。"""
from __future__ import annotations

import os
from pathlib import Path

# 改清洗/標記規則時把版本 +1,就能對舊資料重洗(silver/gold 帶版本欄)
PIPELINE_VERSION = "v1"

ZIP_PATH = os.environ.get(
    "KNOWLEDGE_ZIP",
    "/home/wannavegtour/Desktop/drive-download/line_oa_chat_csv_260605_035144.zip",
)

OLLAMA_URL = "http://localhost:11434/api/chat"
LABEL_MODEL = "gpt-oss:120b"

_CRED = Path("/home/wannavegtour/.hermes/credentials/wannavegtour/knowledge_db.env")


def load_db_config() -> dict:
    cfg = {}
    for line in _CRED.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip()
    return {
        "host": cfg["KNOWLEDGE_DB_HOST"],
        "port": int(cfg["KNOWLEDGE_DB_PORT"]),
        "user": cfg["KNOWLEDGE_DB_USER"],
        "password": cfg["KNOWLEDGE_DB_PASSWORD"],
        "dbname": cfg["KNOWLEDGE_DB_NAME"],
    }
