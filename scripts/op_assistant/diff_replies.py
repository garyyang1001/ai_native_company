#!/usr/bin/env python3
"""Compare new Hermes flow replies vs old standalone listener replies.

Place: scripts/op_assistant/diff_replies.py
Run: .venv/bin/python scripts/op_assistant/diff_replies.py [--limit N] [--threshold 0.85]

Read-only deterministic comparator:
  OLD: events.payload where event_type='op_assistant_line_audit'
  NEW: attempts.output for op-assistant replay attempts

For each source event_id pair:
  - action_match: did both take the same action? (reply / silent / escalate)
  - text_similarity: difflib SequenceMatcher ratio, only when both replied

No LLM calls. No writes.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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

from closed_loop_kernel.store import KernelStore  # noqa: E402


KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]
TARGET_ACTION_MATCH_RATE = 0.95
TARGET_SIMILARITY_PASS_RATE = 0.85


def _validate_kernel_dsn(url: str) -> None:
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
        raise RuntimeError(f"KERNEL_DATABASE_URL points at wrong target; refusing to run. Diff: {diff}")


_validate_kernel_dsn(KERNEL_URL)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return ""


def _normalize_action(value: Any) -> str:
    """Map action labels into canonical {reply, silent, escalate}."""
    if value is None:
        return "silent"
    normalized = str(value).strip().lower()
    if not normalized:
        return "silent"
    if normalized in {"reply", "send", "push", "replied", "respond", "responded"}:
        return "reply"
    if normalized in {"silent", "skip", "skipped", "ignore", "ignored", "none", "no_reply"}:
        return "silent"
    if normalized.startswith("escalate") or normalized in {"escalated", "handoff", "human_review"}:
        return "escalate"
    return "silent"


def _text_similarity(old_text: str, new_text: str) -> float:
    """Return a 0-1 deterministic text similarity ratio after whitespace normalization."""
    old_norm = " ".join((old_text or "").split())
    new_norm = " ".join((new_text or "").split())
    if not old_norm or not new_norm:
        return 0.0
    return difflib.SequenceMatcher(None, old_norm, new_norm).ratio()


def _attempt_columns(store: KernelStore) -> set[str]:
    rows = store.fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'attempts'",
        [],
    )
    return {str(row["column_name"]) for row in rows}


def _attempt_join_filter(columns: set[str], replay_version: str | None = None) -> str:
    """Build the WHERE clause that identifies replay attempts.

    When replay_version is given (e.g. "v2"), require attempts.input.replay_version
    to match — this excludes earlier replay batches with stale logic. Pass None
    to fall back to the legacy marker-detection that allows any historical batch.
    """
    if replay_version:
        # v2 (and later) explicitly marks replay_version in attempts.input.
        # This excludes v1 attempts that ran before the invocation filter existed.
        return f"a.input->>'replay_version' = '{replay_version}'"
    if "agent_id" in columns:
        return "a.agent_id = 'op-assistant-replay'"
    if "profile_id" in columns:
        return "a.profile_id = 'op-assistant-replay'"
    return (
        "(a.output->>'final_action' IS NOT NULL "
        "OR a.output->>'final_draft' IS NOT NULL "
        "OR a.output->>'agent_id' = 'op-assistant-replay' "
        "OR a.input->>'agent_id' = 'op-assistant-replay' "
        "OR a.input->>'profile_id' = 'op-assistant-replay' "
        "OR a.input->>'replay_agent_id' = 'op-assistant-replay')"
    )


def _fetch_pairs(store: KernelStore, limit: int | None, replay_version: str | None = None) -> list[dict[str, Any]]:
    attempt_filter = _attempt_join_filter(_attempt_columns(store), replay_version=replay_version)
    sql = (
        "SELECT e.id AS event_id, e.payload AS audit_payload, "
        "       a.id AS attempt_id, a.status AS attempt_status, a.output AS replay_output "
        "FROM events e "
        "LEFT JOIN LATERAL ("
        "    SELECT a.id, a.status, a.output, a.created_at "
        "    FROM attempts a "
        f"   WHERE a.event_id = e.id AND {attempt_filter} "
        "    ORDER BY a.created_at DESC, a.id DESC "
        "    LIMIT 1"
        ") a ON TRUE "
        "WHERE e.event_type = 'op_assistant_line_audit' "
        "ORDER BY e.created_at, e.id"
    )
    rows = store.fetch_all(sql, [])
    return rows[:limit] if limit is not None else rows


def _old_reply_text(audit: dict[str, Any]) -> str:
    extras = _as_dict(audit.get("extras"))
    return _first_text(
        audit.get("reply_text"),
        audit.get("text_reply"),
        audit.get("reply"),
        audit.get("draft"),
        audit.get("final_draft"),
        extras.get("reply_text"),
        extras.get("text_reply"),
        extras.get("reply"),
        extras.get("draft"),
        extras.get("final_draft"),
    )


def _new_reply_text(replay: dict[str, Any]) -> str:
    return _first_text(
        replay.get("final_draft"),
        replay.get("reply_text"),
        replay.get("text_reply"),
        replay.get("reply"),
        replay.get("draft"),
        replay.get("message"),
    )


def _compare_rows(rows: list[dict[str, Any]], threshold: float, show_fails: int) -> dict[str, Any]:
    pairs = []
    for row in rows:
        audit = _as_dict(row.get("audit_payload"))
        replay = _as_dict(row.get("replay_output")) if row.get("replay_output") else None
        extras = _as_dict(audit.get("extras"))

        old_action = _normalize_action(audit.get("action"))
        old_reply = _old_reply_text(audit)
        new_action = _normalize_action(replay.get("final_action")) if replay else "silent"
        new_reply = _new_reply_text(replay) if replay else ""
        action_match = old_action == new_action

        text_similarity = None
        if old_action == "reply" and new_action == "reply":
            text_similarity = _text_similarity(old_reply, new_reply)

        pairs.append(
            {
                "event_id": str(row.get("event_id")),
                "attempt_id": str(row["attempt_id"]) if row.get("attempt_id") else None,
                "attempt_status": row.get("attempt_status"),
                "audit_text": _first_text(audit.get("text"))[:120],
                "old_action": old_action,
                "old_reply": old_reply[:180],
                "old_skip_reason": _first_text(audit.get("skip_reason")),
                "old_intent": _first_text(audit.get("intent"), extras.get("intent")),
                "new_action": new_action,
                "new_reply": new_reply[:180],
                "new_intent": _first_text(replay.get("intent")) if replay else "",
                "action_match": action_match,
                "text_similarity": text_similarity,
            }
        )

    total = len(pairs)
    action_match_count = sum(1 for pair in pairs if pair["action_match"])
    action_match_rate = action_match_count / total if total else 0.0

    both_replied = [
        pair
        for pair in pairs
        if pair["old_action"] == "reply" and pair["new_action"] == "reply"
    ]
    similarities = [pair["text_similarity"] for pair in both_replied]
    mean_similarity = sum(similarities) / len(similarities) if similarities else None
    similarity_pass_count = sum(1 for similarity in similarities if similarity >= threshold)
    similarity_pass_rate = (
        similarity_pass_count / len(similarities) if similarities else None
    )

    fail_cases = [
        pair
        for pair in pairs
        if not pair["action_match"]
        or (
            pair["text_similarity"] is not None
            and pair["text_similarity"] < threshold
        )
    ]
    fail_cases = sorted(
        fail_cases,
        key=lambda pair: (
            pair["action_match"],
            pair["text_similarity"] if pair["text_similarity"] is not None else 1.0,
            pair["event_id"],
        ),
    )[:show_fails]

    action_pairs = Counter((pair["old_action"], pair["new_action"]) for pair in pairs)
    intent_distribution_new = Counter(pair["new_intent"] for pair in pairs if pair["new_intent"])
    intent_distribution_old = Counter(pair["old_intent"] for pair in pairs if pair["old_intent"])

    return {
        "total_pairs": total,
        "no_attempt_yet": sum(1 for pair in pairs if pair["attempt_status"] is None),
        "action_match_count": action_match_count,
        "action_match_rate": round(action_match_rate, 4),
        "action_pairs_breakdown": [
            {"old": old_action, "new": new_action, "n": count}
            for (old_action, new_action), count in sorted(
                action_pairs.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "both_replied_count": len(both_replied),
        "mean_text_similarity": round(mean_similarity, 4) if mean_similarity is not None else None,
        "similarity_pass_count": similarity_pass_count,
        "similarity_pass_rate": (
            round(similarity_pass_rate, 4) if similarity_pass_rate is not None else None
        ),
        "threshold_used": threshold,
        "intent_distribution_new": dict(intent_distribution_new),
        "intent_distribution_old": dict(intent_distribution_old),
        "comparisons": pairs,
        "fail_cases": [
            {
                "event_id": pair["event_id"],
                "audit_text": pair["audit_text"],
                "old_action": pair["old_action"],
                "old_reply": pair["old_reply"],
                "old_skip_reason": pair["old_skip_reason"],
                "old_intent": pair["old_intent"],
                "new_action": pair["new_action"],
                "new_reply": pair["new_reply"],
                "new_intent": pair["new_intent"],
                "text_similarity": pair["text_similarity"],
            }
            for pair in fail_cases
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Min text similarity to count as similar for matched reply pairs",
    )
    parser.add_argument("--show-fails", type=int, default=10, help="Top N fail cases to print")
    parser.add_argument(
        "--replay-version",
        default="v2",
        help="Only compare against attempts marked with this replay_version (default: v2). "
             "Pass empty string to fall back to legacy any-batch detection.",
    )
    args = parser.parse_args()

    store = KernelStore.from_url(KERNEL_URL)
    try:
        rv = args.replay_version.strip() or None
        rows = _fetch_pairs(store, args.limit, replay_version=rv)
        report = _compare_rows(rows, args.threshold, args.show_fails)
    finally:
        store.close()

    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)

    if report["total_pairs"] == 0:
        return 0
    if report["action_match_rate"] < TARGET_ACTION_MATCH_RATE:
        print(
            f"\naction_match_rate {report['action_match_rate']:.2%} < "
            f"{TARGET_ACTION_MATCH_RATE:.0%} target",
            file=sys.stderr,
        )
        return 2
    similarity_pass_rate = report["similarity_pass_rate"]
    if (
        similarity_pass_rate is not None
        and similarity_pass_rate < TARGET_SIMILARITY_PASS_RATE
    ):
        print(
            f"\nsimilarity_pass_rate {similarity_pass_rate:.2%} < "
            f"{TARGET_SIMILARITY_PASS_RATE:.0%} target",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
