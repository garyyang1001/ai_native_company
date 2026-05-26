# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_daily_curate.py
"""每日 09:00:讀過去 24hr events,gemma4:e4b 整理,寫 summary event,push Telegram

模型呼叫:用 OpenAI 相容 endpoint 直接打 Ollama(localhost:11434/v1)
原因:Hermes auxiliary_client 內部 API(`call_llm`)可選,但直接 HTTP 控制力更大,
fail 模式也清楚。如果之後要切走 Hermes 統一路徑,改 `from agent.auxiliary_client
import call_llm` 即可(API 在 `~/.hermes/hermes-agent/agent/auxiliary_client.py`)。

★ Codex review 修正(v2.1):
- B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載
- M2:summary uuid 改 uuid5(period) 確保 idempotent,cron 重跑不會生重複 summary
- M4:Telegram push 失敗的 exception 不能含 token URL,catch RequestException sanitize
- L1:把 event_count / open_failure_count 也 merge 進 summary dict(否則 push 顯 ?)
"""
import os, json, uuid, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ★ B2 修正(同 ETL)
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

# ★ M2 修正:uuid5 namespace(daily 跟 weekly 各用一個)
DAILY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000002")

# 直接打 Ollama OpenAI-compatible endpoint(跟 Hermes auxiliary.compression 共用模型)
OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
CURATION_MODEL = "gemma4:e4b"  # 跟 auxiliary.compression 同一個 — 不需額外 pull

def run():
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        events = store.fetch_all(
            "SELECT id, payload, created_at FROM events "
            "WHERE event_type = ? AND created_at > ? ORDER BY created_at",
            ["op_assistant_line_message", cutoff_iso]
        )
        failures = store.fetch_all(
            "SELECT id, attempt_id, failure_type, context FROM failures "
            "WHERE status='open' AND created_at > ?",
            [cutoff_iso]
        )

        if not events and not failures:
            return

        # 用 gemma4:e4b 整理(直接 HTTP)
        prompt = _build_curation_prompt(events, failures)
        resp = requests.post(OLLAMA_URL, json={
            "model": CURATION_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,    # 整理任務求穩
        }, timeout=300)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        summary = json.loads(raw)

        # 把 metrics merge 進 summary(L1 修正)
        summary["event_count"] = len(events)
        summary["open_failure_count"] = len(failures)

        # ★ M2 修正:uuid5(period) 確保同一天重跑不會生重複 summary
        period_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sid = str(uuid.uuid5(DAILY_NAMESPACE, period_key))

        # 寫進 events table(不是 candidates!) — ON CONFLICT 保證 idempotent
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [sid, "daily_curation_summary",
             json_param({
                 "period_start": cutoff_iso,
                 "period_end": datetime.now(timezone.utc).isoformat(),
                 "period_key": period_key,
                 "event_count": len(events),
                 "open_failure_count": len(failures),
                 "model": CURATION_MODEL,
                 "patterns": summary.get("patterns", []),
                 "intent_gaps": summary.get("intent_gaps", []),
                 "customer_complaints": summary.get("complaints", []),
                 "actionable_items": summary.get("actionable", []),
             }),
             datetime.now(timezone.utc).isoformat()]
        )
        # Push Telegram(走 Hermes Bot API 直接送 Gary chat)
        _push_telegram_summary(sid, summary)
    finally:
        store.close()

def _build_curation_prompt(events, failures):
    sample = []
    for e in events[:50]:   # 控制 token
        p = e['payload'] if isinstance(e['payload'], dict) else json.loads(e['payload'])
        sample.append({
            "role": p.get('role'),
            "name": p.get('user_name'),
            "text": (p.get('content') or '')[:200]
        })
    fail_list = [{"type": f["failure_type"], "context": f["context"]} for f in failures]
    return f"""你是 wannavegtour OP 助理的「整理員」。讀過去 24hr 對話 + 失敗紀錄,找出:
- patterns: 重複出現的問句或話題
- intent_gaps: 我們的規則表沒抓到的意圖(列原文)
- complaints: 疑似客訴或不滿(列原文)
- actionable: 你建議要修的事(具體建議)

對話:{json.dumps(sample, ensure_ascii=False)}
失敗:{json.dumps(fail_list, ensure_ascii=False)}

只回 JSON,key: patterns / intent_gaps / complaints / actionable,值為陣列。"""

def _push_telegram_summary(summary_event_id, summary):
    """直接打 Telegram Bot API,不需要走 Hermes gateway(這是後台 script)。

    ★ M4 修正:catch RequestException,sanitize 不洩 token URL。
    """
    bot_token = _get_telegram_bot_token()
    chat_id = _get_telegram_home_channel()
    if not bot_token or not chat_id:
        # graceful no-op:也寫 health event 讓 Gary 知道為何沒收到通知
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_skipped",
                 json_param({"reason": "missing token or chat_id",
                             "has_token": bool(bot_token), "has_chat": bool(chat_id),
                             "summary_event_id": summary_event_id}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass
        return

    text = (
        f"📋 OP 對話日整理 ({datetime.now().strftime('%Y-%m-%d')})\n"
        f"事件數: {summary.get('event_count', 0)} / 待修 failures: {summary.get('open_failure_count', 0)}\n\n"
        f"🔁 重複 pattern: {len(summary.get('patterns', []))} 筆\n"
        f"❓ 意圖 gap: {len(summary.get('intent_gaps', []))} 筆\n"
        f"📣 客訴: {len(summary.get('customer_complaints', []))} 筆\n"
        f"💡 我建議: {len(summary.get('actionable_items', []))} 筆\n\n"
        f"細節查 events.id={summary_event_id}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        # ★ M4:exception message 可能含 token URL,只 log status code + message preview
        status = getattr(e.response, "status_code", None) if hasattr(e, "response") and e.response else None
        sanitized = f"telegram push failed: status={status}, type={type(e).__name__}"
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_failure",
                 json_param({"summary_event_id": summary_event_id, "error": sanitized}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass

def _get_telegram_bot_token():
    """從 default profile 的 .env 讀(or 從 op-assistant 設定的 escalate token)"""
    # Codex 階段確認讀法
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return None
    for line in open(env_path):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

def _get_telegram_home_channel():
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return None
    for line in open(env_path):
        if line.startswith("TELEGRAM_HOME_CHANNEL="):
            return line.split("=", 1)[1].strip()
    return None

if __name__ == "__main__":
    run()
