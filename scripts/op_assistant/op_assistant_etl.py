# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_etl.py
# (NOT ~/.hermes/scripts/ — hermes cron --profile 解析在 profile 內 scripts/)
"""每 4 hr:Hermes session.db 新訊息 → kernel events(含 user_id resolve + UUID dedup)

session.db 真實 schema(verified 2026-05-26):
  CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,             -- 'user' / 'assistant' / 'tool' / 'system'
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,        -- ★ Unix epoch(不是 ISO string)
    token_count INTEGER,
    finish_reason TEXT,
    platform_message_id TEXT,       -- ★ LINE 用這欄 dedup
    observed INTEGER DEFAULT 0
  );
  CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,           -- 'line' / 'telegram' / 'cli' etc.
    user_id TEXT,
    started_at REAL NOT NULL,
    ...
  );

★ Codex review 修正(v2.1):
- B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載
- H3:SQLite WAL 模式不可 immutable=1(可能讀不到最新 WAL frame),
       改 mode=ro + busy_timeout
"""
import sqlite3, os, json, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ★ B2 修正:手動載入 profile .env(--no-agent cron 不會自動載)
def _load_profile_env():
    env_path = Path("/home/wannavegtour/.hermes/profiles/op-assistant/.env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

_load_profile_env()

from closed_loop_kernel.store import KernelStore, json_param

# 用絕對路徑(--no-agent script 的 $HOME 被 scheduler 改成 profile home,
# 用 ~/... 可能展開到 profile dir 而非 user home)
SESSION_DB = "/home/wannavegtour/.hermes/profiles/op-assistant/state.db"
MAPPING_PATH = "/home/wannavegtour/.hermes/credentials/wannavegtour/op_mapping.json"
KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]   # 沒設 = crash(嚴格,不要 silent fallback)

# UUID5 namespace 用 op-assistant 固定 UUID(避免每次跑 dedup 失敗)
ETL_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000001")

def _load_mapping():
    """缺檔 → 空 dict;檔壞 → 寫健康事件後也回空 dict,不擋 ETL"""
    if not os.path.exists(MAPPING_PATH):
        return {"user_id_to_name": {}, "group_id_to_name": {}}
    try:
        with open(MAPPING_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # ★ Codex review M1 修正:malformed JSON 寫健康事件而非 silent crash
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "op_mapping_load_failure",
                 json_param({"path": MAPPING_PATH, "error": str(e)}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass
        return {"user_id_to_name": {}, "group_id_to_name": {}}

def run():
    mapping = _load_mapping()
    user_map = mapping.get("user_id_to_name", {})
    group_map = mapping.get("group_id_to_name", {})

    # ★ timestamp 是 Unix epoch REAL,要 epoch 不是 ISO
    cutoff_epoch = (datetime.now(timezone.utc) - timedelta(hours=4)).timestamp()

    # ★ H3 修正:WAL 模式 immutable=1 不安全;改 mode=ro + busy_timeout
    conn = sqlite3.connect(
        f"file:{SESSION_DB}?mode=ro", uri=True,
        timeout=30.0,          # busy_timeout 30s(等 Hermes 寫完)
    )
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.id, m.session_id, m.role, m.content,
               m.tool_calls, m.tool_name, m.timestamp,
               m.platform_message_id,
               s.source, s.user_id
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.timestamp > ?
          AND s.source = 'line'
        ORDER BY m.timestamp
    """, (cutoff_epoch,)).fetchall()
    conn.close()

    if not rows:
        return

    store = KernelStore.from_url(KERNEL_URL)
    try:
        for r in rows:
            # ★ 用 uuid5 + platform_message_id (LINE) 或 fallback msg_id 做 deterministic UUID
            dedup_key = r["platform_message_id"] or f"hermes_msg_{r['id']}"
            event_id = str(uuid.uuid5(ETL_NAMESPACE, dedup_key))

            uid = r["user_id"]
            payload = {
                "role": r["role"],
                "content": r["content"],
                "tool_calls": json.loads(r["tool_calls"]) if r["tool_calls"] else None,
                "tool_name": r["tool_name"],
                "platform_message_id": r["platform_message_id"],
                "session_id": r["session_id"],
                "user_id": uid,
                "user_name": user_map.get(uid, "未知 OP"),
                "group_name": group_map.get(r["session_id"], "未知群"),  # session.id 對 group 看實際情況
                "source": r["source"],
            }
            # ★ timestamp 從 REAL 轉成 ISO 給 PG TIMESTAMPTZ
            created_iso = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).isoformat()

            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [event_id, "op_assistant_line_message", json_param(payload), created_iso]
            )
    finally:
        store.close()

if __name__ == "__main__":
    run()
