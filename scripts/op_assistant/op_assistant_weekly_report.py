# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_weekly_report.py
"""每週一 09:00:過去 7 天統計 + Gary 批准趨勢 + 推 Telegram

★ Codex review 修正(v2.1):
- B2:手動載 profile .env
- M2:weekly summary uuid 改 uuid5(week_key) 確保 idempotent
- M3:_push_weekly_report 完整實作(不留 pass,避免 cron 假動作)
"""
import os, json, uuid, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# B2 修正
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

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]

# M2 修正
WEEKLY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000003")

def run():
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        # 1. 訊息總數 / 各意圖分佈
        intent_dist = store.fetch_all(
            "SELECT payload->>'intent' AS intent, COUNT(*) AS n "
            "FROM events JOIN attempts ON attempts.event_id = events.id "
            "WHERE events.created_at > ? GROUP BY payload->>'intent' "
            "ORDER BY n DESC",
            [week_start]
        )
        # 2. 失敗 top types
        fail_top = store.fetch_all(
            "SELECT failure_type, COUNT(*) AS n FROM failures "
            "WHERE created_at > ? GROUP BY failure_type ORDER BY n DESC LIMIT 10",
            [week_start]
        )
        # 3. Gary 批准了多少 / 駁回多少
        approvals = store.fetch_all(
            "SELECT decision, COUNT(*) AS n FROM approvals "
            "WHERE created_at > ? GROUP BY decision",
            [week_start]
        )
        # 4. Gary 最常批准什麼 patch_type(學進去的方向)
        approved_types = store.fetch_all(
            "SELECT c.patch_type, COUNT(*) AS n FROM approvals a "
            "JOIN improvement_candidates c ON a.candidate_id = c.id "
            "WHERE a.decision='approved' AND a.created_at > ? "
            "GROUP BY c.patch_type ORDER BY n DESC",
            [week_start]
        )

        # ★ M2 修正:uuid5(week_key) idempotent
        week_key = datetime.now(timezone.utc).strftime("%G-W%V")   # ISO week
        wid = str(uuid.uuid5(WEEKLY_NAMESPACE, week_key))
        payload = {
            "period_start": week_start,
            "period_key": week_key,
            "intent_distribution": [dict(r) for r in intent_dist],
            "top_failures": [dict(r) for r in fail_top],
            "approvals": [dict(r) for r in approvals],
            "approved_patch_types": [dict(r) for r in approved_types],
        }
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [wid, "weekly_report", json_param(payload),
             datetime.now(timezone.utc).isoformat()]
        )
        _push_weekly_report(wid, payload)
    finally:
        store.close()

def _push_weekly_report(weekly_event_id, payload):
    """★ M3 修正:real push,not pass。同 daily,sanitize exception。"""
    bot_token = _get_telegram_bot_token()
    chat_id = _get_telegram_home_channel()
    if not bot_token or not chat_id:
        return

    intents = payload["intent_distribution"][:5]
    intents_str = "\n  ".join(f"- {i['intent']}: {i['n']}" for i in intents) or "(無)"
    fails = payload["top_failures"][:5]
    fails_str = "\n  ".join(f"- {f['failure_type']}: {f['n']}" for f in fails) or "(無)"
    apps = {a["decision"]: a["n"] for a in payload["approvals"]}

    text = (
        f"📊 OP 週報 ({payload['period_key']})\n\n"
        f"訊息意圖 TOP5:\n  {intents_str}\n\n"
        f"失敗類型 TOP5:\n  {fails_str}\n\n"
        f"你批准了 {apps.get('approved', 0)} 筆,駁回 {apps.get('rejected', 0)} 筆\n\n"
        f"細節 events.id={weekly_event_id}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        status = getattr(e.response, "status_code", None) if hasattr(e, "response") and e.response else None
        store = KernelStore.from_url(KERNEL_URL)
        try:
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_failure",
                 json_param({"weekly_event_id": weekly_event_id,
                             "error": f"weekly push failed status={status} type={type(e).__name__}"}),
                 datetime.now(timezone.utc).isoformat()]
            )
        finally:
            store.close()

# 共用 Telegram helpers(同 daily_curate.py)
def _get_telegram_bot_token():
    p = "/home/wannavegtour/.hermes/.env"
    if not os.path.exists(p): return None
    for line in open(p):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

def _get_telegram_home_channel():
    p = "/home/wannavegtour/.hermes/.env"
    if not os.path.exists(p): return None
    for line in open(p):
        if line.startswith("TELEGRAM_HOME_CHANNEL="):
            return line.split("=", 1)[1].strip()
    return None

if __name__ == "__main__":
    run()
