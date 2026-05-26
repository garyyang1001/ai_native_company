#!/usr/bin/env python3
"""Replay listener audit JSONL into closed_loop_kernel events.

放這:scripts/op_assistant/replay_audit_to_kernel.py
跑:.venv/bin/python scripts/op_assistant/replay_audit_to_kernel.py [--dry-run] [--limit N] [--source PATH]

★ 一次性工具,不是 cron。把過去 listener 留下的 wannavegtour.jsonl 灌進 kernel events,
   供 pre-launch test (diff_replies.py) 對照新 Hermes 流程的 reply。

★ event_type = "op_assistant_line_audit"(跟 ETL 的 op_assistant_line_message 區分)
★ uuid5 deterministic dedup → 多次 replay 不會重複插入
★ DSN guard 同 ETL,防誤打 CRM PG
"""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

DEFAULT_JSONL = "/home/wannavegtour/.hermes/line_events/wannavegtour.jsonl"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
    """防止 replay 誤打 CRM 或別的 PG。"""
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

AUDIT_REPLAY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000004")
EVENT_TYPE = "op_assistant_line_audit"


def _warn(message: str) -> None:
    print(f"WARN: {message}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", default=DEFAULT_JSONL)
    args = parser.parse_args()

    stats = {
        "lines_read": 0,
        "lines_inserted": 0,
        "lines_skipped_no_msgid": 0,
        "lines_dup_skipped": 0,
        "lines_parse_error": 0,
    }
    store = None if args.dry_run else KernelStore.from_url(KERNEL_URL)
    try:
        with open(args.source, "r", encoding="utf-8") as f:
            for idx, raw in enumerate(f):
                if args.limit is not None and idx >= args.limit:
                    break
                stats["lines_read"] += 1
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError as e:
                    stats["lines_parse_error"] += 1
                    _warn(f"line {idx + 1}: JSON parse failed: {e.msg}")
                    continue

                msg_id = d.get("message_id")
                if not msg_id:
                    stats["lines_skipped_no_msgid"] += 1
                    _warn(f"line {idx + 1}: missing message_id, skipped")
                    continue

                event_id = str(uuid.uuid5(AUDIT_REPLAY_NAMESPACE, str(msg_id)))
                if args.dry_run:
                    continue

                result = store.fetch_one(
                    "INSERT INTO events (id, event_type, payload, created_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING RETURNING id",
                    [event_id, EVENT_TYPE, json_param(d), d["ts"]],
                )
                if result:
                    stats["lines_inserted"] += 1
                else:
                    stats["lines_dup_skipped"] += 1
    finally:
        if store is not None:
            store.close()

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
