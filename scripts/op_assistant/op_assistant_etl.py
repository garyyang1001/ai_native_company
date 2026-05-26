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

★ Codex review v2.1 修正(2026-05-26 上午):
- B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載
- H3:SQLite WAL 模式不可 immutable=1(可能讀不到最新 WAL frame),
       改 mode=ro + busy_timeout

★ Codex review Wave 1 修正(2026-05-26 下午):
- HIGH#1:durable cursor + PG retry(原 4hr sliding window 若 PG down >4hr 會永遠掉訊息)
       新策略:查 kernel events table 最大 created_at,沒就 fallback 7 天,
       widen window + uuid5 ON CONFLICT 自然去重
- HIGH#2:SQLite open/query 包 try/except,寫 op_etl_read_failure event,不擋 cron
"""
import sqlite3, os, json, uuid, time
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

# 用絕對路徑(--no-agent script 的 $HOME 被 scheduler 改成 profile home)
SESSION_DB = "/home/wannavegtour/.hermes/profiles/op-assistant/state.db"
MAPPING_PATH = "/home/wannavegtour/.hermes/credentials/wannavegtour/op_mapping.json"
KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]

# UUID5 namespace 用 op-assistant 固定 UUID(deterministic dedup)
ETL_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000001")
HEALTH_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-00000000000a")

# Wave 1 HIGH#1:cursor fallback 寬度(若 query max 失敗或 events 表空)
FALLBACK_LOOKBACK_DAYS = 7

# ----- HIGH#1: PG retry helper -----
def _with_pg_retry(fn, attempts=3, base_backoff=1.5):
    """簡單 retry:psycopg.OperationalError 重試。其他 exception 直接 raise。"""
    import psycopg
    last = None
    for i in range(attempts):
        try:
            return fn()
        except psycopg.OperationalError as e:
            last = e
            if i < attempts - 1:
                time.sleep(base_backoff ** i)
    raise last


def _load_mapping():
    """缺檔 / list-shaped / malformed → 空 dict + 寫 health event,不擋 ETL"""
    if not os.path.exists(MAPPING_PATH):
        return {"user_id_to_name": {}, "group_id_to_name": {}}
    try:
        with open(MAPPING_PATH) as f:
            data = json.load(f)
        # MEDIUM 修:也驗 dict shape(Codex 提的)
        if not isinstance(data, dict):
            raise ValueError(f"expected dict, got {type(data).__name__}")
        return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        try:
            store = KernelStore.from_url(KERNEL_URL)
            # 失敗事件也 deterministic(防同一錯誤 重複健康噪音)
            err_class = type(e).__name__
            hid = str(uuid.uuid5(HEALTH_NAMESPACE, f"mapping_load_{err_class}"))
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [hid, "op_mapping_load_failure",
                 json_param({"path": MAPPING_PATH, "error_class": err_class, "error": str(e)[:200]}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass
        return {"user_id_to_name": {}, "group_id_to_name": {}}


def _get_cursor_epoch(store):
    """HIGH#1:查 kernel events table 最後一筆 op_assistant_line_message 的 created_at;
    沒查到 → 7 天前。
    這比固定 4hr 窗安全 — PG 重啟久了也能補上漏的 message。"""
    try:
        row = _with_pg_retry(lambda: store.fetch_one(
            "SELECT MAX(created_at) AS last_ts FROM events "
            "WHERE event_type = 'op_assistant_line_message'"
        ))
        if row and row.get("last_ts"):
            # row.last_ts 是 datetime 或 ISO string,統一轉 epoch
            last_ts = row["last_ts"]
            if isinstance(last_ts, str):
                last_ts = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            return last_ts.timestamp()
    except Exception:
        pass
    return (datetime.now(timezone.utc) - timedelta(days=FALLBACK_LOOKBACK_DAYS)).timestamp()


def _write_health_event(store, key: str, payload: dict):
    """寫 deterministic health event(per Codex M5 修正:不重複噪音)"""
    try:
        hid = str(uuid.uuid5(HEALTH_NAMESPACE, key))
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [hid, key.split("_", 1)[0] + "_failure" if "failure" not in key else key,
             json_param(payload),
             datetime.now(timezone.utc).isoformat()]
        )
    except Exception:
        pass


def _read_session_messages(cursor_epoch):
    """HIGH#2:SQLite open/query 包 try/except,失敗 raise sqlite3.Error 給上層處理。"""
    conn = sqlite3.connect(
        f"file:{SESSION_DB}?mode=ro", uri=True,
        timeout=30.0,
    )
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        return conn.execute("""
            SELECT m.id, m.session_id, m.role, m.content,
                   m.tool_calls, m.tool_name, m.timestamp,
                   m.platform_message_id,
                   s.source, s.user_id
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.timestamp > ?
              AND s.source = 'line'
            ORDER BY m.timestamp
        """, (cursor_epoch,)).fetchall()
    finally:
        conn.close()


def run():
    mapping = _load_mapping()
    user_map = mapping.get("user_id_to_name", {})
    group_map = mapping.get("group_id_to_name", {})

    # HIGH#1:先連 kernel 拿 cursor + retry
    try:
        store = _with_pg_retry(lambda: KernelStore.from_url(KERNEL_URL))
    except Exception as e:
        # PG 連不到 = 整個 ETL 沒法做。沒地方寫 health event,只能 raise。
        # cron logger 會記 stderr。
        raise

    try:
        cursor_epoch = _get_cursor_epoch(store)

        # HIGH#2:SQLite read 包 try/except,失敗寫 health event,return 不繼續寫 PG
        try:
            rows = _read_session_messages(cursor_epoch)
        except sqlite3.Error as e:
            _write_health_event(store, "op_etl_read_failure",
                {"db": SESSION_DB, "cursor_epoch": cursor_epoch,
                 "error_class": type(e).__name__, "error": str(e)[:200]})
            return

        if not rows:
            return

        for r in rows:
            # uuid5 + platform_message_id (LINE) 或 fallback msg_id 做 deterministic UUID
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
                "group_name": group_map.get(r["session_id"], "未知群"),
                "source": r["source"],
            }
            created_iso = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).isoformat()

            # PG insert 也包 retry(避免單筆 transient fail)
            _with_pg_retry(lambda eid=event_id, p=payload, ci=created_iso: store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [eid, "op_assistant_line_message", json_param(p), ci]
            ))
    finally:
        store.close()

if __name__ == "__main__":
    run()
