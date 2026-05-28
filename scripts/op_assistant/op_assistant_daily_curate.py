"""Daily 09:00 — gemma4 curates past 24hr OP traffic + pushes Telegram summary.

V0.2 era (2026-05-28+):data shape comes from attempt_envelopes + failures,
not the V0.1 `events.op_assistant_line_message` placeholder.

Reads:
- events 'op_assistant_line_inbound' for raw inbound count
- attempt_envelopes JOIN attempts for decision distribution (task / intent / reply_kind)
- failures for trigger-hit cases

Writes:
- events 'daily_curation_summary' (one per period_key, idempotent uuid5)
- events 'telegram_push_failure' if push fails (sanitized)

Pushes:
- Telegram via Bot API directly (not via Hermes gateway — this is post-process)

★ B2:--no-agent cron 不會 auto-load profile .env
★ M2:uuid5(period_key) idempotency
★ M4:Telegram error sanitization (no token leak in logs)
★ Karpathy 原則 2:gemma4 prompt 只送 redacted_preview,不送 raw text
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


# ★ B2 — manual dotenv load
def _load_profile_env() -> None:
    env_path = Path("/home/wannavegtour/.hermes/profiles/op-assistant/.env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _load_hermes_env() -> None:
    """Load Telegram creds from Hermes default-profile .env."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_profile_env()
_load_hermes_env()

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]
DAILY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000002")
OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
CURATION_MODEL = "gemma4:e4b"
PROFILE_ID = "op-assistant-line"
MAX_PROMPT_INBOUND = 50      # cap prompt tokens
MAX_PROMPT_FAILURES = 30


def _read_window(store: KernelStore) -> tuple[list, list, list]:
    inbound = store.fetch_all(
        "SELECT id, payload, created_at FROM events "
        "WHERE event_type = 'op_assistant_line_inbound' "
        "AND created_at > NOW() - INTERVAL '24 hours' "
        "ORDER BY created_at"
    )
    envelopes = store.fetch_all(
        "SELECT e.task_id, e.run_id, e.machine_record, a.status, a.created_at "
        "FROM attempt_envelopes e JOIN attempts a ON a.id = e.attempt_id "
        "WHERE e.profile_id = ? "
        "AND a.created_at > NOW() - INTERVAL '24 hours' "
        "ORDER BY a.created_at",
        [PROFILE_ID],
    )
    failures = store.fetch_all(
        "SELECT f.id, f.failure_type, f.context, f.created_at "
        "FROM failures f "
        "WHERE f.created_at > NOW() - INTERVAL '24 hours' "
        "AND f.status = 'open' "
        "ORDER BY f.created_at"
    )
    return inbound, envelopes, failures


def _build_prompt(envelopes: list, failures: list) -> str:
    samples = []
    for env in envelopes[-MAX_PROMPT_INBOUND:]:
        mr = env.get("machine_record")
        if isinstance(mr, str):
            try:
                mr = json.loads(mr)
            except Exception:
                mr = {}
        mr = mr or {}
        samples.append({
            "intent": mr.get("parser_intent"),
            "reply_kind": mr.get("reply_kind"),
            "fallback_path": mr.get("fallback_path"),
            "msg_preview": (mr.get("message_preview_redacted") or "")[:120],
            "task_continuation": mr.get("task_continuation"),
        })

    fail_summary = []
    for f in failures[:MAX_PROMPT_FAILURES]:
        ctx = f.get("context") or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = {}
        fail_summary.append({
            "type": f.get("failure_type"),
            "domain_code": ctx.get("domain_failure_code"),
            "trigger_reason": ctx.get("trigger_reason"),
            "msg_preview": (ctx.get("message_preview_redacted") or "")[:120],
        })

    return f"""你是阿玩旅遊 OP bot 的「整理員」。讀過去 24hr 的 bot 決策樣本 + 失敗紀錄,找出:

- patterns: 重複出現的問句或話題類型(列關鍵字 + 預估次數)
- intent_gaps: parser 沒抓到但訊息預覽看起來有意圖的 case(列 msg_preview)
- actionable: 你建議要改 query_parser.py 加什麼 keyword / regex / intent

決策樣本(最多 {MAX_PROMPT_INBOUND} 筆):
{json.dumps(samples, ensure_ascii=False, indent=2)}

失敗紀錄(最多 {MAX_PROMPT_FAILURES} 筆):
{json.dumps(fail_summary, ensure_ascii=False, indent=2)}

只回 JSON object,key 必須是: patterns / intent_gaps / actionable,值為陣列(可空)。"""


def _call_gemma4(prompt: str) -> dict:
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": CURATION_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        },
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return json.loads(raw)


_TYPE_ZH = {"keyword": "關鍵字", "regex": "句型", "intent": "意圖"}


def _render_telegram_text(summary: dict, summary_event_id: str) -> str:
    """Compose the human-readable Telegram daily report.

    Gary 在路上滑手機看,所以:不寫 attempt/failure/intent_gap 這類技術詞,
    講「客人發了幾句、bot 處理幾通、沒聽懂哪幾句」。末段保留 8 字短編號,
    Gary 回家可丟給 agent 查 events.id。
    """
    date_str = datetime.now().strftime("%-m/%-d")
    inbound = int(summary.get("inbound_count") or 0)
    attempts = int(summary.get("attempt_count") or 0)
    fail_count = int(summary.get("open_failure_count") or 0)
    fail_previews = summary.get("fail_previews") or []
    patterns = summary.get("patterns") or []
    actionable = summary.get("actionable") or []

    lines = [f"📋 阿玩 OP 助手日報 {date_str}", ""]
    if inbound == 0 and attempts == 0:
        lines.append("今天沒收到客人訊息。")
    else:
        lines.append(f"今天客人發 {inbound} 句話進來,bot 處理 {attempts} 通。")
    lines.append("")

    if fail_count > 0:
        lines.append(f"❓ 有 {fail_count} 通 bot 沒聽懂:")
        for p in fail_previews[:3]:
            lines.append(f"「{p}」")
        lines.append("")

    if patterns:
        top = patterns[0]
        kw = (top.get("keyword") or "").strip()
        cnt = int(top.get("estimated_count") or 0)
        if cnt >= 2 and kw:
            lines.append(f"💡 看完今天的對話,「{kw}」這個詞被問 {cnt} 次,")
            lines.append("bot 還不會認。")
            lines.append("")

    if actionable:
        lines.append(f"我建議讓 bot 學 {len(actionable)} 招:")
        for i, a in enumerate(actionable[:5], 1):
            kind_zh = _TYPE_ZH.get(a.get("type") or "", a.get("type") or "規則")
            val = (a.get("value") or "").strip()
            reason = (a.get("reason") or "").strip()
            if reason:
                lines.append(f"{i}. {kind_zh}「{val}」— {reason}")
            else:
                lines.append(f"{i}. {kind_zh}「{val}」")
        lines.append("")
        lines.append("你 OK 我就改。")
        lines.append("")

    short_id = summary_event_id.split("-", 1)[0] if "-" in summary_event_id else summary_event_id[:8]
    lines.append(f"(技術細節編號:{short_id} — 給 agent 查用)")
    return "\n".join(lines)


def _push_telegram(store: KernelStore, summary_event_id: str, summary: dict) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL")

    if not bot_token or not chat_id:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()), "telegram_push_skipped",
                json_param({
                    "reason": "missing token or chat_id",
                    "has_token": bool(bot_token),
                    "has_chat": bool(chat_id),
                    "summary_event_id": summary_event_id,
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return

    text = _render_telegram_text(summary, summary_event_id)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        sanitized = f"telegram push failed: status={status}, type={type(exc).__name__}"
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()), "telegram_push_failure",
                json_param({"summary_event_id": summary_event_id, "error": sanitized}),
                datetime.now(timezone.utc).isoformat(),
            ],
        )


def run() -> None:
    store = KernelStore.from_url(KERNEL_URL)
    try:
        inbound, envelopes, failures = _read_window(store)

        if not inbound and not envelopes and not failures:
            print("daily curate: no traffic in past 24hr, skip")
            return

        try:
            summary = _call_gemma4(_build_prompt(envelopes, failures))
        except Exception as exc:
            summary = {
                "patterns": [],
                "intent_gaps": [],
                "actionable": [],
                "_gemma_error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

        summary["inbound_count"] = len(inbound)
        summary["attempt_count"] = len(envelopes)
        summary["open_failure_count"] = len(failures)
        summary["model"] = CURATION_MODEL

        fail_previews: list[str] = []
        for f in failures[:5]:
            ctx = f.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except Exception:
                    ctx = {}
            preview = (ctx.get("message_preview_redacted") or "").strip()
            if preview:
                fail_previews.append(preview[:120])
        summary["fail_previews"] = fail_previews

        period_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary_event_id = str(uuid.uuid5(DAILY_NAMESPACE, period_key))

        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [
                summary_event_id, "daily_curation_summary",
                json_param({
                    "period_key": period_key,
                    "period_end": datetime.now(timezone.utc).isoformat(),
                    "inbound_count": summary["inbound_count"],
                    "attempt_count": summary["attempt_count"],
                    "open_failure_count": summary["open_failure_count"],
                    "model": CURATION_MODEL,
                    "patterns": summary.get("patterns", []),
                    "intent_gaps": summary.get("intent_gaps", []),
                    "actionable": summary.get("actionable", []),
                    "fail_previews": summary.get("fail_previews", []),
                    "gemma_error": summary.get("_gemma_error"),
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )

        _push_telegram(store, summary_event_id, summary)

        print(
            f"daily curate {period_key}: inbound={summary['inbound_count']} "
            f"attempts={summary['attempt_count']} failures={summary['open_failure_count']} "
            f"patterns={len(summary.get('patterns', []))} gaps={len(summary.get('intent_gaps', []))}"
        )
    finally:
        store.close()


if __name__ == "__main__":
    run()
