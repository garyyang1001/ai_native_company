#!/usr/bin/env python3
"""Replay past LINE events through the new Hermes 6-tool harness (dry-run send).

放這:scripts/op_assistant/replay_through_op_assistant.py
跑:.venv/bin/python scripts/op_assistant/replay_through_op_assistant.py [--limit N] [--dry-run]

★ 讀 kernel events 表的 op_assistant_line_audit 事件
★ 對每筆,呼叫 6-tool chain(send_reply 強制 dry_run=True)
★ 寫 attempts 紀錄(intent / draft / validation / latency)
★ 不發 real LINE/Telegram/WC API beyond tool-level fail-safes
★ Pre-launch test 的 stage 1 — 之後 diff_replies.py 把這份新 reply 跟舊 listener reply 比對

Schema:
  events:  id (UUID), event_type, payload (JSONB), created_at
           audit payload contains: message_id, text, action, intent (legacy), user_id, group_id, ts
  attempts: id, event_id, status, input (JSONB), output (JSONB), error_message, created_at

Use uuid5 with REPLAY_NAMESPACE keyed by source event_id so re-runs are idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


_load_profile_env()

# Load plugin tools — production deploy lives at ~/.hermes/plugins/op-assistant-tools/
_PLUGIN_DIR = "/home/wannavegtour/.hermes/plugins/op-assistant-tools"
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# Also need wannavegtour repo on path for tools.py imports.
_REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import tools  # type: ignore  # noqa: E402
from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402


KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]
REPLAY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000005")  # legacy v1 — kept for record
REPLAY_V2_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000007")  # v2: invocation filter only
REPLAY_V3_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000008")  # v3: + help_request fast path
REPLAY_V4_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000009")  # v4: validate exemption (buggy, NameError)
REPLAY_V5_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-00000000000a")  # v5: validate exemption (fixed)
INBOUND_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000006")  # mirrors fork plugin
MAX_RETRY = 3
AGENT_ID = "op-assistant-replay"
REPLAY_VERSION = "v5"
DEFAULT_INVOCATION_PREFIXES = ("小弟", "@小弟", "/小弟")


def _detect_invocation(text: str, mention_is_self: bool, prefixes: tuple = DEFAULT_INVOCATION_PREFIXES) -> dict | None:
    """Mirrors plugins/op-assistant-line/adapter.py LineAdapter._detect_invocation.

    Keep this in sync with the fork plugin. Pure deterministic — Code is Law.
    """
    if mention_is_self:
        return {"kind": "mention"}
    text_stripped = (text or "").strip()
    for prefix in prefixes:
        if text_stripped.startswith(prefix):
            after = text_stripped[len(prefix):]
            if (
                not after
                or after[0].isspace()
                or after.startswith("?")
                or after.startswith("？")
            ):
                return {"kind": f"prefix:{prefix}", "token": prefix}
    return None


def _strip_invocation_token(text: str, invocation: dict) -> str:
    """Mirror fork plugin _strip_invocation_token. Length=0 for mention case = remove prefix entirely."""
    if invocation["kind"] == "mention":
        return text.strip()
    token = invocation.get("token", "")
    if token and text.lstrip().startswith(token):
        return text.lstrip()[len(token):].strip()
    return text.strip()


def _validate_kernel_dsn(url: str) -> None:
    """Refuse to run unless KERNEL_DATABASE_URL points at the op-assistant kernel."""
    from urllib.parse import urlparse

    expected = {
        "host": "127.0.0.1",
        "port": 5434,
        "db": "op_assistant_kernel",
        "user": "op_kernel",
    }
    parsed = urlparse(url)
    actual = {
        "host": parsed.hostname,
        "port": parsed.port,
        "db": parsed.path.lstrip("/"),
        "user": parsed.username,
    }
    if actual != expected:
        diff = {
            key: f"got={actual.get(key)!r} want={expected[key]!r}"
            for key in expected
            if actual.get(key) != expected[key]
        }
        raise RuntimeError(f"DSN mismatch; refusing to run replay. Diff: {diff}")


_validate_kernel_dsn(KERNEL_URL)


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _tool_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    raw = getattr(tools, tool_name)(args)
    return _loads(raw)


def _attempt_id_for_event(event_id: str) -> str:
    """v4 attempt_id — uses REPLAY_V4_NAMESPACE so it doesn't collide with v1/v2/v3 rows."""
    return str(uuid.uuid5(REPLAY_V5_NAMESPACE, str(event_id)))


def _write_inbound_event(store: KernelStore, event_id: str, payload: dict[str, Any]) -> bool:
    """Mirrors fork plugin _log_inbound_to_kernel. Always log inbound for learning data.

    Called for silent observations (no invocation) — we still record the message
    in events table so weekly_curate / failure analyzer can see the full conversation.
    """
    msg_id = payload.get("message_id") or f"no-msg-id-{event_id}"
    inbound_id = str(uuid.uuid5(INBOUND_NAMESPACE, str(msg_id)))
    inbound_payload = {
        "message_id": msg_id,
        "text": payload.get("text", ""),
        "message_type": payload.get("message_type"),
        "chat_type": "group",
        "group_id": payload.get("group_id", ""),
        "user_id": payload.get("user_id", ""),
        "mention_is_self": payload.get("mention_is_self", False),
        "received_at": payload.get("ts") or datetime.now(timezone.utc).isoformat(),
        "source_event_id": event_id,
        "via": "replay_v2",
    }
    row = store.fetch_one(
        "INSERT INTO events (id, event_type, payload, created_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING RETURNING id",
        [
            inbound_id,
            "op_assistant_line_inbound",
            json_param(inbound_payload),
            datetime.now(timezone.utc).isoformat(),
        ],
    )
    return row is not None


def _insert_attempt(
    store: KernelStore,
    *,
    attempt_id: str,
    event_id: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any] | None,
    status: str,
    error_message: str | None = None,
    write: bool = True,
) -> bool:
    if not write:
        return False

    row = store.fetch_one(
        "INSERT INTO attempts (id, event_id, status, input, output, error_message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO NOTHING RETURNING id",
        [
            attempt_id,
            event_id,
            status,
            json_param(input_payload),
            json_param(output_payload) if output_payload is not None else None,
            error_message,
            datetime.now(timezone.utc).isoformat(),
        ],
    )
    return row is not None


def _base_input_payload(event_id: str, payload: dict[str, Any], cleaned_text: str | None = None) -> dict[str, Any]:
    return {
        "agent_id": AGENT_ID,
        "replay_version": REPLAY_VERSION,
        "tool_name": "hermes_6_tool_chain",
        "source": "op_assistant_line_audit_replay",
        "original_event_id": event_id,
        "message_id": payload.get("message_id"),
        "text": payload.get("text", ""),
        "cleaned_text": cleaned_text if cleaned_text is not None else payload.get("text", ""),
        "group_id": payload.get("group_id", "TEST_GROUP_DRYRUN"),
        "user_id": payload.get("user_id", "unknown"),
        "legacy_intent": payload.get("intent"),
        "legacy_action": payload.get("action"),
    }


def _record_failed_attempt(
    store: KernelStore,
    *,
    audit_event: dict[str, Any],
    payload: dict[str, Any],
    error: BaseException,
    chain_log: list[dict[str, Any]],
    started_at: float,
    write: bool,
) -> dict[str, Any]:
    event_id = str(audit_event["id"])
    attempt_id = _attempt_id_for_event(event_id)
    latency_ms = int((time.monotonic() - started_at) * 1000)
    error_text = "".join(traceback.format_exception_only(type(error), error)).strip()
    inserted = _insert_attempt(
        store,
        attempt_id=attempt_id,
        event_id=event_id,
        input_payload=_base_input_payload(event_id, payload),
        output_payload={
            "agent_id": AGENT_ID,
            "chain": chain_log,
            "final_action": "failed",
            "latency_ms": latency_ms,
            "status": "failed",
        },
        status="failed",
        error_message=error_text[:2000],
        write=write,
    )
    return {
        "replayed": False,
        "attempt_id": attempt_id,
        "inserted": inserted,
        "final_action": "failed",
        "latency_ms": latency_ms,
        "error": error_text,
    }


def replay_one(store: KernelStore, audit_event: dict[str, Any], *, write: bool = True) -> dict[str, Any]:
    """Replay one event through the 6-tool chain. Safe to call multiple times."""
    event_id = str(audit_event["id"])
    payload = _loads(audit_event["payload"])
    if not isinstance(payload, dict):
        raise RuntimeError(f"event payload is not an object: {event_id}")

    attempt_id = _attempt_id_for_event(event_id)
    if write and store.fetch_one("SELECT id FROM attempts WHERE id = ?", [attempt_id]):
        return {"duplicate": True, "attempt_id": attempt_id}

    text = str(payload.get("text") or "")
    group_id = payload.get("group_id") or "TEST_GROUP_DRYRUN"
    message_type = payload.get("message_type")

    input_payload = _base_input_payload(event_id, payload)

    if message_type not in ("text", None):
        output_payload = {
            "agent_id": AGENT_ID,
            "original_event_id": event_id,
            "final_action": "skipped",
            "skip_reason": f"non-text message: {message_type}",
            "status": "success",
        }
        inserted = _insert_attempt(
            store,
            attempt_id=attempt_id,
            event_id=event_id,
            input_payload=input_payload,
            output_payload=output_payload,
            status="success",
            write=write,
        )
        return {"skipped": True, "attempt_id": attempt_id, "inserted": inserted, "reason": output_payload["skip_reason"]}

    if not text.strip():
        output_payload = {
            "agent_id": AGENT_ID,
            "original_event_id": event_id,
            "final_action": "skipped",
            "skip_reason": "empty text",
            "status": "success",
        }
        inserted = _insert_attempt(
            store,
            attempt_id=attempt_id,
            event_id=event_id,
            input_payload=_base_input_payload(event_id, payload, cleaned_text=""),
            output_payload=output_payload,
            status="success",
            write=write,
        )
        return {"skipped": True, "attempt_id": attempt_id, "inserted": inserted, "reason": "empty text"}

    # ──────────────────────────────────────────────────────────────────
    # Invocation filter (Code is Law) — mirrors fork plugin behavior:
    #   plugins/op-assistant-line/adapter.py _detect_invocation
    # Silent observations: write op_assistant_line_inbound event, do NOT run 6-tool chain,
    #   do NOT write attempts. Matches what production fork plugin will do.
    # ──────────────────────────────────────────────────────────────────
    mention_is_self = bool(payload.get("mention_is_self"))
    invocation = _detect_invocation(text, mention_is_self)
    if invocation is None:
        inserted_inbound = False
        if write:
            inserted_inbound = _write_inbound_event(store, event_id, payload)
        return {
            "silent_observe": True,
            "attempt_id": None,
            "event_id": event_id,
            "inserted_inbound": inserted_inbound,
            "reason": "no_invocation",
        }
    cleaned_text = _strip_invocation_token(text, invocation)
    text = cleaned_text  # downstream sees cleaned text only

    # Update input payload to include invocation + cleaned_text for audit trail.
    input_payload = _base_input_payload(event_id, payload, cleaned_text=cleaned_text)
    input_payload["invocation"] = invocation

    t0 = time.monotonic()
    chain_log: list[dict[str, Any]] = []

    try:
        intent_result = _tool_call("query_intent", {"text": text})
        chain_log.append({"tool": "query_intent", "output": intent_result})
        intent = intent_result.get("intent")
        confidence = float(intent_result.get("confidence") or 0)
        entities = intent_result.get("entities") if isinstance(intent_result.get("entities"), dict) else {}

        if intent == "unknown" or confidence < 0.5:
            esc = _tool_call(
                "escalate_to_gary",
                {
                    "reason": f"intent={intent} confidence={confidence}",
                    "context": {
                        "original_text": text,
                        "intent": intent,
                        "source_event_id": event_id,
                    },
                    "group_id": group_id,
                    "dry_run": True,
                },
            )
            chain_log.append({"tool": "escalate_to_gary", "output": esc})
            latency_ms = int((time.monotonic() - t0) * 1000)
            output_payload = {
                "agent_id": AGENT_ID,
                "original_event_id": event_id,
                "chain": chain_log,
                "intent": intent,
                "draft": None,
                "validation": None,
                "send_result": esc,
                "final_action": "escalate",
                "latency_ms": latency_ms,
                "status": "success",
            }
            inserted = _insert_attempt(
                store,
                attempt_id=attempt_id,
                event_id=event_id,
                input_payload=input_payload,
                output_payload=output_payload,
                status="success",
                write=write,
            )
            return {
                "replayed": True,
                "attempt_id": attempt_id,
                "inserted": inserted,
                "final_action": "escalate",
                "intent": intent,
                "latency_ms": latency_ms,
            }

        fetch_result = _tool_call("fetch_wc_data", {"intent": intent, "entities": entities})
        chain_log.append({"tool": "fetch_wc_data", "output": fetch_result})

        if fetch_result.get("error") and not fetch_result.get("data"):
            esc = _tool_call(
                "escalate_to_gary",
                {
                    "reason": "fetch_wc_data failed",
                    "context": {
                        "original_text": text,
                        "intent": intent,
                        "wc_error": str(fetch_result.get("error"))[:200],
                        "source_event_id": event_id,
                    },
                    "group_id": group_id,
                    "dry_run": True,
                },
            )
            chain_log.append({"tool": "escalate_to_gary", "output": esc})
            latency_ms = int((time.monotonic() - t0) * 1000)
            output_payload = {
                "agent_id": AGENT_ID,
                "original_event_id": event_id,
                "chain": chain_log,
                "intent": intent,
                "draft": None,
                "validation": None,
                "send_result": esc,
                "final_action": "escalate_wc_fail",
                "latency_ms": latency_ms,
                "status": "success",
            }
            inserted = _insert_attempt(
                store,
                attempt_id=attempt_id,
                event_id=event_id,
                input_payload=input_payload,
                output_payload=output_payload,
                status="success",
                write=write,
            )
            return {
                "replayed": True,
                "attempt_id": attempt_id,
                "inserted": inserted,
                "final_action": "escalate_wc_fail",
                "intent": intent,
                "latency_ms": latency_ms,
            }

        data = fetch_result.get("data") if isinstance(fetch_result.get("data"), dict) else {}

        draft = ""
        validate_result: dict[str, Any] = {"passed": False, "violations": ["validate_not_run"]}
        last_violations: list[Any] = []
        for retry in range(MAX_RETRY):
            compose_result = _tool_call("compose_reply", {"intent": intent, "data": data})
            chain_log.append({"tool": "compose_reply", "retry": retry, "output": compose_result})
            draft = str(compose_result.get("draft_reply_body") or "")

            validate_result = _tool_call("validate_reply", {"draft": draft, "intent": intent, "data": data})
            chain_log.append({"tool": "validate_reply", "retry": retry, "output": validate_result})

            if validate_result.get("passed"):
                break
            last_violations = validate_result.get("violations", [])

        if not validate_result.get("passed"):
            esc = _tool_call(
                "escalate_to_gary",
                {
                    "reason": f"compose-validate exhausted after {MAX_RETRY} retries",
                    "context": {
                        "original_text": text,
                        "intent": intent,
                        "violations": last_violations,
                        "source_event_id": event_id,
                    },
                    "group_id": group_id,
                    "dry_run": True,
                },
            )
            chain_log.append({"tool": "escalate_to_gary", "output": esc})
            latency_ms = int((time.monotonic() - t0) * 1000)
            output_payload = {
                "agent_id": AGENT_ID,
                "original_event_id": event_id,
                "chain": chain_log,
                "intent": intent,
                "draft": draft,
                "validation": validate_result,
                "send_result": esc,
                "final_action": "escalate_validate_fail",
                "latency_ms": latency_ms,
                "status": "success",
            }
            inserted = _insert_attempt(
                store,
                attempt_id=attempt_id,
                event_id=event_id,
                input_payload=input_payload,
                output_payload=output_payload,
                status="success",
                write=write,
            )
            return {
                "replayed": True,
                "attempt_id": attempt_id,
                "inserted": inserted,
                "final_action": "escalate_validate_fail",
                "intent": intent,
                "latency_ms": latency_ms,
            }

        send_result = _tool_call(
            "send_reply",
            {
                "group_id": group_id,
                "draft": draft,
                "dry_run": True,
            },
        )
        chain_log.append({"tool": "send_reply", "output": send_result})
        latency_ms = int((time.monotonic() - t0) * 1000)
        output_payload = {
            "agent_id": AGENT_ID,
            "original_event_id": event_id,
            "chain": chain_log,
            "intent": intent,
            "draft": draft,
            "validation": validate_result,
            "send_result": send_result,
            "final_action": "send",
            "latency_ms": latency_ms,
            "status": "success",
        }
        inserted = _insert_attempt(
            store,
            attempt_id=attempt_id,
            event_id=event_id,
            input_payload=input_payload,
            output_payload=output_payload,
            status="success",
            write=write,
        )
        return {
            "replayed": True,
            "attempt_id": attempt_id,
            "inserted": inserted,
            "final_action": "send",
            "intent": intent,
            "draft": draft,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return _record_failed_attempt(
            store,
            audit_event=audit_event,
            payload=payload,
            error=exc,
            chain_log=chain_log,
            started_at=t0,
            write=write,
        )


def _update_stats(stats: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get("duplicate"):
        stats["duplicates"] += 1
        return
    if result.get("skipped"):
        stats["skipped"] += 1
        return
    if result.get("inserted"):
        stats["db_inserted"] += 1

    final_action = result.get("final_action", "n/a")
    intent = result.get("intent", "n/a")
    if final_action == "send":
        stats["replayed_success"] += 1
    elif final_action == "failed":
        stats["failed"] += 1
    else:
        stats["replayed_escalate"] += 1

    stats["by_intent"][intent] = stats["by_intent"].get(intent, 0) + 1
    stats["by_action"][final_action] = stats["by_action"].get(final_action, 0) + 1
    if "latency_ms" in result:
        stats["latencies_ms"].append(result["latency_ms"])


def _finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    if stats["latencies_ms"]:
        lats = sorted(stats["latencies_ms"])
        stats["latency_p50_ms"] = lats[len(lats) // 2]
        stats["latency_p95_ms"] = lats[int(len(lats) * 0.95)] if len(lats) >= 20 else lats[-1]
        stats["latency_max_ms"] = lats[-1]
    del stats["latencies_ms"]
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Process only first N audit events")
    parser.add_argument("--dry-run", action="store_true", help="Run tool chain, but do not write attempts")
    args = parser.parse_args()

    store = KernelStore.from_url(KERNEL_URL)
    try:
        audit_events = store.fetch_all(
            "SELECT id, payload, created_at FROM events "
            "WHERE event_type = 'op_assistant_line_audit' "
            "ORDER BY created_at",
            [],
        )
        if args.limit is not None:
            audit_events = audit_events[: args.limit]

        stats: dict[str, Any] = {
            "total": len(audit_events),
            "dry_run": args.dry_run,
            "db_inserted": 0,
            "duplicates": 0,
            "replayed_success": 0,
            "replayed_escalate": 0,
            "failed": 0,
            "skipped": 0,
            "by_intent": {},
            "by_action": {},
            "latencies_ms": [],
        }

        for event in audit_events:
            result = replay_one(store, dict(event), write=not args.dry_run)
            _update_stats(stats, result)

        print(json.dumps(_finalize_stats(stats), indent=2, ensure_ascii=False, sort_keys=True))
    finally:
        store.close()


if __name__ == "__main__":
    main()
