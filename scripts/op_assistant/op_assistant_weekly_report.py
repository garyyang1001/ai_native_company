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

def _validate_kernel_dsn(url: str) -> None:
    """★ Wave 2 HIGH#K1:防止 cron 誤打 CRM 或別的 PG。
    Parse DSN,要求 host/port/db/user 都跟 op-assistant-kernel 一致,不對立刻 raise。
    """
    from urllib.parse import urlparse
    EXPECTED = {"host": "127.0.0.1", "port": 5434, "db": "op_assistant_kernel", "user": "op_kernel"}
    try:
        p = urlparse(url)
        actual = {"host": p.hostname, "port": p.port, "db": p.path.lstrip("/"), "user": p.username}
    except Exception as e:
        raise RuntimeError(f"KERNEL_DATABASE_URL parse failed: {type(e).__name__}: {e}") from e
    if actual != EXPECTED:
        # 不 print actual 完整值(防洩漏);只 print 哪幾欄不符
        diff = {k: f"got={actual.get(k)!r} want={EXPECTED[k]!r}" for k in EXPECTED if actual.get(k) != EXPECTED[k]}
        raise RuntimeError(
            f"KERNEL_DATABASE_URL points at wrong target — refusing to run. "
            f"Mismatch: {diff}. "
            f"This guard exists to prevent op-assistant cron from accidentally writing to wannavegtourcrm-postgres-audit (port 5433) or other PG instances."
        )

_validate_kernel_dsn(KERNEL_URL)

# M2 修正
WEEKLY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000003")
HEALTH_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-00000000000a")

def run():
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        # 1. 訊息總數 / 各意圖分佈
        # ★ Wave 2 MEDIUM-bug-B 修:intent 在 attempts.output(6 tool 實作後才會寫),
        # 不是 events.payload。本 query 在 6 tool 上線前會回空 — 那是 expected。
        intent_dist = store.fetch_all(
            "SELECT output->>'intent' AS intent, COUNT(*) AS n "
            "FROM attempts "
            "WHERE created_at > ? AND status = 'success' AND output IS NOT NULL "
            "GROUP BY output->>'intent' "
            "ORDER BY n DESC NULLS LAST",
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
        # ★ Wave 1 HIGH#4:RETURNING id — 只在真插入時才 push
        result = store.fetch_one(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING RETURNING id",
            [wid, "weekly_report", json_param(payload),
             datetime.now(timezone.utc).isoformat()]
        )
        if result:
            _push_weekly_report(wid, payload)
        # else: 重跑同週 — 不再 push
    finally:
        store.close()

def _push_weekly_report(weekly_event_id, payload):
    """★ M3 修正:real push,not pass。同 daily,sanitize exception。"""
    bot_token = _get_telegram_bot_token()
    chat_id = _get_telegram_home_channel()
    if not bot_token or not chat_id:
        # ★ Wave 1 LOW + Wave 2 重整:try/finally 保 connection close
        store = None
        try:
            store = KernelStore.from_url(KERNEL_URL)
            week_key = payload.get("period_key", "?")
            hid = str(uuid.uuid5(HEALTH_NAMESPACE, f"weekly_push_skipped_{week_key}"))
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [hid, "telegram_push_skipped",
                 json_param({"reason": "missing token or chat_id",
                             "has_token": bool(bot_token), "has_chat": bool(chat_id),
                             "weekly_event_id": weekly_event_id,
                             "period_key": week_key}),
                 datetime.now(timezone.utc).isoformat()]
            )
        except Exception:
            pass
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
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
        store = None
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_failure",
                 json_param({"weekly_event_id": weekly_event_id,
                             "error": f"weekly push failed status={status} type={type(e).__name__}"}),
                 datetime.now(timezone.utc).isoformat()]
            )
        except Exception:
            pass
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

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
