"""
OHYA 整合端到端 demo orchestrator。

把 OHYA kanban.db → ohya_kernel → FailureAnalyzer → Telegram 中介整條鏈路串起來。

執行：
  KERNEL_DATABASE_URL=postgresql:///ohya_kernel \\
  python3 -m closed_loop_kernel.ohya_demo \\
    --kanban-db /path/to/ohya/kanban.db \\
    --chat-id 6005789080
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

from .event_reporter import EventReporter
from .failure_analyzer import FailureAnalyzer
from .ohya_approval_bot import OhyaApprovalBot, load_env, DEFAULT_ENV_PATH
from .ohya_seed import seed_ohya
from .store import KernelStore


DEMO_TASK_ID = "demo-ohya-cms-draft-failure-001"
DEMO_TASK_TITLE = "PayloadCMS 文章發布 (demo failure)"
DEMO_TASK_PROFILE = "cms-draft-executor"


def seed_demo_failure_into_kanban(kanban_db_path: str) -> dict:
    """
    在修好的 kanban.db 塞一筆模擬失敗（cms-draft-executor crash on Zeabur timeout）。
    Idempotent：用固定 task_id 防重複。
    回傳寫入的 task_id / task_run_id。
    """
    conn = sqlite3.connect(kanban_db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM tasks WHERE id = ?", (DEMO_TASK_ID,))
        if cur.fetchone() is None:
            now = int(time.time())
            cur.execute(
                """
                INSERT INTO tasks (id, title, status, priority, created_at, workspace_kind, tenant, consecutive_failures)
                VALUES (?, ?, 'archived', 0, ?, 'scratch', 'ohya', 1)
                """,
                (DEMO_TASK_ID, DEMO_TASK_TITLE, now - 120),
            )
            cur.execute(
                """
                INSERT INTO task_runs (task_id, profile, status, outcome, started_at, ended_at, error, summary, metadata)
                VALUES (?, ?, 'crashed', 'crashed', ?, ?, ?, ?, ?)
                """,
                (
                    DEMO_TASK_ID,
                    DEMO_TASK_PROFILE,
                    now - 100,
                    now - 80,
                    "ConnectionError: Zeabur API timeout after 60s — PayloadCMS draft write failed",
                    "Failed to write article draft post_id=4751 to PayloadCMS",
                    json.dumps({"post_id": 4751, "endpoint": "/api/posts"}),
                ),
            )
            run_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO task_events (task_id, run_id, kind, payload, created_at)
                VALUES (?, ?, 'created', ?, ?)
                """,
                (DEMO_TASK_ID, run_id, json.dumps({"source": "ohya_demo"}), now - 120),
            )
            cur.execute(
                """
                INSERT INTO task_events (task_id, run_id, kind, payload, created_at)
                VALUES (?, ?, 'archived', ?, ?)
                """,
                (DEMO_TASK_ID, run_id, json.dumps({"reason": "crashed"}), now - 80),
            )
            conn.commit()
            return {"task_id": DEMO_TASK_ID, "task_run_id": run_id, "seeded": True}
        return {"task_id": DEMO_TASK_ID, "task_run_id": None, "seeded": False}
    finally:
        conn.close()


def run_demo(
    kanban_db_path: str,
    chat_id: int | None = None,
    env_path: Path = DEFAULT_ENV_PATH,
    skip_telegram: bool = False,
) -> dict:
    kernel_url = _database_url()
    result: dict = {"steps": []}

    # Step 1：塞 demo failure 到 kanban.db
    seed_result = seed_demo_failure_into_kanban(kanban_db_path)
    result["steps"].append({"step": "seed_demo_failure_into_kanban", "result": seed_result})

    # Step 2：seed OHYA team + agents (idempotent)
    store = KernelStore.from_url(kernel_url)
    try:
        seed_meta = seed_ohya(store)
        result["steps"].append({"step": "seed_ohya_team_and_agents", "team_id": seed_meta["team_id"], "agent_count": len(seed_meta["agents"])})

        # Step 3：EventReporter sync from kanban → ohya_kernel
        reporter = EventReporter(kanban_db_path=kanban_db_path, kernel_url=kernel_url, tenant_default="ohya")
        sync_result = reporter.sync()
        result["steps"].append({
            "step": "event_reporter_sync",
            "events_imported": sync_result.events_imported,
            "attempts_imported": sync_result.attempts_imported,
            "failures_opened": sync_result.failures_opened,
            "last_event_id": sync_result.last_event_id,
            "last_run_id": sync_result.last_run_id,
            "skipped_rows": len(sync_result.skipped_rows),
        })

        # Step 4：FailureAnalyzer 把 open failures 轉成 candidates
        analyzer = FailureAnalyzer(store)
        analyze_result = analyzer.analyze_open_failures()
        result["steps"].append({
            "step": "failure_analyzer",
            "processed": analyze_result["processed"],
            "skipped": analyze_result["skipped"],
            "candidate_ids": analyze_result["candidates"],
        })

        # Step 5：Telegram dispatch
        if skip_telegram:
            result["steps"].append({"step": "telegram_dispatch", "skipped": True, "reason": "--skip-telegram flag"})
        else:
            env = load_env(env_path)
            token = env.get("TELEGRAM_BOT_TOKEN")
            if not token:
                raise RuntimeError(f"TELEGRAM_BOT_TOKEN not in {env_path}")
            if chat_id is None:
                raise RuntimeError("chat_id required (pass --chat-id) — getUpdates discovery currently blocked by skimm3r918_bot polling conflict")
            bot = OhyaApprovalBot(bot_token=token, kernel_url=kernel_url, chat_id=chat_id)
            dispatched = bot.dispatch_pending_approvals(store)
            result["steps"].append({"step": "telegram_dispatch", "dispatched": dispatched, "chat_id": chat_id})
    finally:
        store.close()

    return result


def _database_url() -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise RuntimeError("KERNEL_DATABASE_URL is required")
    return url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OHYA integration end-to-end demo")
    parser.add_argument("--kanban-db", required=True, help="path to OHYA kanban.db (must be writable)")
    parser.add_argument("--chat-id", type=int, default=None, help="Gary's Telegram chat_id")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--skip-telegram", action="store_true", help="run pipeline without pushing to Telegram")
    args = parser.parse_args()

    result = run_demo(
        kanban_db_path=args.kanban_db,
        chat_id=args.chat_id,
        env_path=Path(args.env),
        skip_telegram=args.skip_telegram,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
