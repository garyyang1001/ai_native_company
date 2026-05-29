"""V0.3 Phase 4 + 5 — Telegram callback dispatcher.

When Gary taps an inline-keyboard button, Telegram POSTs an update with
``callback_query`` to ``/telegram/webhook``. Phase 1 already audit-logs
that update into ``events.telegram_inbound``; this module turns it into
a durable approval / rejection / view / kill decision in the kernel and
replies in Telegram so Gary sees the result of his tap.

Contract sources:

* ``docs/contracts/op_assistant_v0.3/callback_data_v0.md`` — the
  ``<action>:<candidate_uuid_hex32>`` and ``killall:<daily_summary_id>``
  format we expect.
* ``docs/contracts/op_assistant_v0.3/approval_audit_v0.md`` — the
  atomic SELECT-FOR-UPDATE → INSERT approval → UPDATE candidate →
  INSERT event transaction.

Code is Rule:every routing decision in this module is deterministic
Python. The only LLM that ever touched any of the data we act on was
gemma4 back in Phase 2 (as a Proposer); nothing here calls an LLM.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402


# ---------------------------------------------------------------------------
# Callback parsing (per callback_data_v0.md)
# ---------------------------------------------------------------------------

CALLBACK_PER_CANDIDATE_RE = re.compile(
    r"^(apv|rej|vw|kill):([0-9a-f]{32})$"
)
CALLBACK_KILLALL_RE = re.compile(r"^killall:([0-9a-f]{32})$")


def parse_callback_data(data: str) -> tuple[str, str] | None:
    """Return ``(action, target_id_hex32)`` or ``None`` for malformed input.

    ``target_id_hex32`` is the candidate id (for apv/rej/vw/kill) or the
    daily summary id (for killall). Both are 32-char lowercase hex.
    """
    if not isinstance(data, str):
        return None
    m = CALLBACK_PER_CANDIDATE_RE.fullmatch(data)
    if m:
        return m.group(1), m.group(2)
    m = CALLBACK_KILLALL_RE.fullmatch(data)
    if m:
        return "killall", m.group(1)
    return None


def hex32_to_uuid(hex32: str) -> str:
    """Re-insert dashes so the 32-hex form matches PG UUID storage."""
    return (
        f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-"
        f"{hex32[16:20]}-{hex32[20:32]}"
    )


# ---------------------------------------------------------------------------
# Atomic claim (per approval_audit_v0.md §dispatcher transactional claim)
# ---------------------------------------------------------------------------

class ClaimResult(str, Enum):
    OK = "ok"
    STALE = "stale"
    ALREADY_CLAIMED = "already_claimed"
    UNKNOWN_CANDIDATE = "unknown_candidate"


_STATUS_EXPECTED_FROM = {
    "approved": "draft",
    "rejected": "draft",
    "killed": "applied",
}


def claim_and_apply(store: KernelStore, *,
                     source_event_id: str,
                     candidate_id: str,
                     decision: str,
                     approved_by: str,
                     channel_message_id: str | None = None,
                     reject_reason: str | None = None) -> ClaimResult:
    """Atomic SELECT-FOR-UPDATE → INSERT approval → UPDATE candidate →
    INSERT audit event. The whole sequence rolls back together on any
    failure inside the transaction.
    """
    assert decision in _STATUS_EXPECTED_FROM, f"unsupported decision: {decision!r}"
    expected_from = _STATUS_EXPECTED_FROM[decision]
    now_iso = datetime.now(timezone.utc).isoformat()

    with store.transaction() as tx:
        # 0. Lock the candidate row.
        cand = tx.execute(
            "SELECT status FROM improvement_candidates "
            "WHERE id = ? FOR UPDATE",
            [candidate_id],
        ).fetchone()
        if cand is None:
            return ClaimResult.UNKNOWN_CANDIDATE
        current_status = cand["status"] if isinstance(cand, dict) else cand[0]
        if current_status != expected_from:
            # Stale click — write events but never approvals.
            tx.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    "telegram_callback_stale",
                    json_param({
                        "candidate_id": candidate_id,
                        "source_event_id": source_event_id,
                        "current_status": current_status,
                        "expected_from": expected_from,
                        "attempted_decision": decision,
                        "by_actor": approved_by,
                    }),
                    now_iso,
                ],
            )
            return ClaimResult.STALE

        # 1. INSERT approvals row.
        approval_id = str(uuid.uuid4())
        approval_row = tx.execute(
            "INSERT INTO approvals ("
            "id, candidate_id, approved_by, decision, comments, "
            "approval_channel, source_event_id, channel_message_id, "
            "reject_reason, created_at"
            ") VALUES (?, ?, ?, ?, NULL, 'telegram', ?, ?, ?, ?) "
            "ON CONFLICT (source_event_id) DO NOTHING "
            "RETURNING id",
            [
                approval_id, candidate_id, approved_by, decision,
                source_event_id, channel_message_id, reject_reason, now_iso,
            ],
        ).fetchone()
        if approval_row is None:
            return ClaimResult.ALREADY_CLAIMED

        # 2. UPDATE candidate.status.
        next_status = {
            "approved": "approved",
            "rejected": "rejected",
            "killed": "killed",
        }[decision]
        tx.execute(
            "UPDATE improvement_candidates SET status = ? WHERE id = ?",
            [next_status, candidate_id],
        )

        # 3. Audit event same transaction.
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": expected_from,
                    "to_status": next_status,
                    "by_phase": "phase_4_dispatcher",
                    "by_actor": approved_by,
                    "approval_id": approval_id,
                }),
                now_iso,
            ],
        )
    return ClaimResult.OK


# ---------------------------------------------------------------------------
# UX reply text (per approval_audit_v0.md §reject UX & §view UX)
# ---------------------------------------------------------------------------

_TYPE_PRETTY = {
    "availability_keyword": "關鍵字",
    "availability_regex": "句型",
}


def _candidate_summary(store: KernelStore, candidate_id: str) -> tuple[str, str]:
    """Return (typed_payload_summary, candidate_status) for replies."""
    row = store.fetch_one(
        "SELECT status, proposal_type, typed_payload "
        "FROM improvement_candidates WHERE id = ?",
        [candidate_id],
    )
    if row is None:
        return "(找不到候選)", "missing"
    typed = row.get("typed_payload")
    if isinstance(typed, str):
        typed = json.loads(typed)
    label = _TYPE_PRETTY.get(row.get("proposal_type"), "建議")
    value = (typed or {}).get("value", "?")
    return f"{label}「{value}」", row.get("status") or "?"


def render_reply(action: str, claim: ClaimResult,
                  store: KernelStore, candidate_id: str) -> str:
    if claim == ClaimResult.UNKNOWN_CANDIDATE:
        return "❓ 找不到這條候選紙條(可能已被清除)"
    summary, status = _candidate_summary(store, candidate_id)
    if claim == ClaimResult.ALREADY_CLAIMED:
        return f"⏭ 這個按鈕已經處理過了({summary},目前狀態:{status})"
    if claim == ClaimResult.STALE:
        return (
            f"⏭ 已過期({summary},目前狀態:{status})\n"
            f"這條建議已經不在等待批准的狀態。如果你想重新處理,"
            f"明天 09:00 gemma4 整理時看到同樣訊息會再提一次。"
        )
    # OK path
    if action == "apv":
        return (
            f"✅ 已批准{summary}\n\n"
            f"接下來會發生:\n"
            f"• 系統把這條建議拿去實驗室跑 4 個指標(舊規則沒打壞 / 至少救回 1 條 /\n"
            f"  沒同句多意圖 / 沒太貪 30 天 unclear)\n"
            f"• 4 個都過 → bot 規則新增這條\n"
            f"• 任一不過 → 自動退回,不會影響 bot"
        )
    if action == "rej":
        return (
            f"❌ 已拒絕{summary}\n\n"
            f"接下來會發生:\n"
            f"• 這條建議狀態改成「拒絕」,不會進實驗室,不會改 bot 規則\n"
            f"• 30 天後 events 自動清掉\n"
            f"• 明天 gemma4 如果再提同樣建議,系統會自動跳過不重複建"
        )
    if action == "killed":
        return (
            f"💥 已 KILL{summary}\n\n"
            f"接下來會發生:\n"
            f"• 已套用的 patch 自動 git revert\n"
            f"• bot 規則回到 KILL 前的狀態\n"
            f"• canary 標記 killed,不再 sample 流量"
        )
    return f"✅ 已處理({summary})"


# ---------------------------------------------------------------------------
# Sandbox replay trigger (Phase 4 → Phase 6)
# ---------------------------------------------------------------------------

def trigger_sandbox_replay(store: KernelStore, kernel_url: str,
                            candidate_id: str) -> dict[str, Any] | None:
    """Approved candidates fan out into the replay engine. Phase 6 picks
    the result up by reading ``sandbox_runs``; we also UPDATE the
    candidate's status here so downstream phases see the right state.
    Returns the replay result dict for caller logging, or None if
    something prevented the run.
    """
    try:
        from importlib.util import spec_from_file_location, module_from_spec
        path = (
            Path(REPO_PATH) / "scripts" / "op_assistant"
            / "op_assistant_sandbox_replay.py"
        )
        spec = spec_from_file_location("op_sandbox_replay_dispatch", path)
        if spec is None or spec.loader is None:
            return None
        mod = module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        result = mod.run_sandbox_replay(
            candidate_id=candidate_id,
            target_db_url=kernel_url,
        )
    except Exception as exc:  # noqa: BLE001 — never let replay crash the webhook reply
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "sandbox_replay_error",
                json_param({
                    "candidate_id": candidate_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:200],
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return None

    next_status = "sandbox_verified" if result["status"] == "passed" else "sandbox_failed"
    with store.transaction() as tx:
        tx.execute(
            "UPDATE improvement_candidates SET status = ? "
            "WHERE id = ? AND status = 'approved'",
            [next_status, candidate_id],
        )
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": "approved",
                    "to_status": next_status,
                    "by_phase": "phase_6_sandbox_replay",
                    "by_actor": "system",
                    "sandbox_run_id": result["run_id"],
                    "fail_reason": result.get("fail_reason"),
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
    return result


def render_sandbox_followup(result: dict[str, Any], summary: str) -> str:
    """The post-replay message Gary sees once the lab finishes."""
    if result["status"] == "passed":
        m = result["metrics"]
        return (
            f"🔬 sandbox 已通過 ({summary})\n"
            f"• 舊規則沒打壞: {m['regression_count']} 條 ✅\n"
            f"• 新救回失敗: {m['improvement_count']} 條 ✅\n"
            f"• 30 天 unclear 命中率: {m['over_greedy_rate']*100:.1f}% ✅\n"
            f"等 Phase 7 寫 patch + Phase 8 canary,bot 就會真的學會"
        )
    return (
        f"🔬 sandbox 沒通過 ({summary})\n"
        f"原因: {result.get('fail_reason', '?')}\n"
        f"bot 不會更新,這條候選標記為 sandbox_failed"
    )


# ---------------------------------------------------------------------------
# Top-level dispatch (the function the webhook background task calls)
# ---------------------------------------------------------------------------

def dispatch_callback(*,
                       store: KernelStore,
                       kernel_url: str,
                       source_event_id: str,
                       callback_query: dict[str, Any]) -> dict[str, Any]:
    """Process one Telegram callback_query end-to-end.

    Returns ``{action, claim, reply_text, sandbox_result?}`` so the
    caller can post the reply (and any follow-up) to Telegram.
    """
    data = (callback_query or {}).get("data") or ""
    parsed = parse_callback_data(data)
    if parsed is None:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "telegram_callback_malformed",
                json_param({
                    "source_event_id": source_event_id,
                    "raw_data_len": len(data),
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return {
            "action": None,
            "claim": None,
            "reply_text": "❓ 沒看懂這個按鈕。請按主訊息上的按鈕,不要轉發舊訊息。",
        }

    action, target_id_hex = parsed
    actor = str((callback_query.get("from") or {}).get("id") or "unknown")
    channel_msg_id = str(callback_query.get("id") or "")

    if action == "vw":
        candidate_uuid = hex32_to_uuid(target_id_hex)
        row = store.fetch_one(
            "SELECT status, metrics::text AS metrics_text, fail_reason "
            "FROM sandbox_runs WHERE candidate_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [candidate_uuid],
        )
        if row is None:
            summary, _ = _candidate_summary(store, candidate_uuid)
            return {
                "action": action,
                "claim": None,
                "reply_text": (
                    f"🔬 sandbox 還沒跑過 ({summary})。\n"
                    f"先按 ✅ 批准會自動觸發 sandbox。"
                ),
            }
        return {
            "action": action,
            "claim": None,
            "reply_text": _render_view_reply(store, candidate_uuid, row),
        }

    if action in ("apv", "rej"):
        candidate_uuid = hex32_to_uuid(target_id_hex)
        decision = "approved" if action == "apv" else "rejected"
        claim = claim_and_apply(
            store,
            source_event_id=source_event_id,
            candidate_id=candidate_uuid,
            decision=decision,
            approved_by=actor,
            channel_message_id=channel_msg_id,
        )
        reply = render_reply(action, claim, store, candidate_uuid)
        result: dict[str, Any] = {
            "action": action,
            "claim": claim.value if isinstance(claim, Enum) else claim,
            "reply_text": reply,
        }
        if action == "apv" and claim == ClaimResult.OK:
            sandbox = trigger_sandbox_replay(store, kernel_url, candidate_uuid)
            if sandbox is not None:
                summary, _ = _candidate_summary(store, candidate_uuid)
                result["sandbox_result"] = sandbox
                result["sandbox_followup"] = render_sandbox_followup(
                    sandbox, summary,
                )
        return result

    if action in ("kill", "killall"):
        # Phase 8 territory — not in scope this round. Audit-log and tell
        # Gary the feature isn't online yet so he doesn't think he was
        # ignored.
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "telegram_callback_unsupported",
                json_param({
                    "action": action,
                    "target_id_hex": target_id_hex,
                    "source_event_id": source_event_id,
                    "by_actor": actor,
                }),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return {
            "action": action,
            "claim": None,
            "reply_text": (
                "⚠️ KILL 還沒實作(Phase 8 才會開)。"
                "如果真的需要緊急退回,先在電腦上 git revert。"
            ),
        }

    # Defensive default — should never reach here because parse_callback_data
    # only returns the action whitelist above.
    return {
        "action": action,
        "claim": None,
        "reply_text": f"❓ 未知的動作: {action}",
    }


def _render_view_reply(store: KernelStore, candidate_uuid: str,
                        sandbox_row: dict[str, Any]) -> str:
    summary, _ = _candidate_summary(store, candidate_uuid)
    metrics_text = sandbox_row.get("metrics_text") or "{}"
    try:
        metrics = json.loads(metrics_text)
    except Exception:
        metrics = {}
    if sandbox_row.get("status") == "passed":
        return (
            f"🔬 sandbox 通過 ({summary})\n"
            f"• 舊規則沒打壞: {metrics.get('regression_count', '?')}\n"
            f"• 新救回失敗: {metrics.get('improvement_count', '?')}\n"
            f"• 過去 30 天 unclear 命中率: "
            f"{(metrics.get('over_greedy_rate', 0))*100:.1f}%"
        )
    return (
        f"🔬 sandbox 沒過 ({summary})\n"
        f"原因: {sandbox_row.get('fail_reason') or '?'}"
    )
