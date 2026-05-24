"""
Scenario 1 (SQL self-healing) 可重跑 demo。

對應文件：scenarios/sql-self-healing-v0.md

故事線：
  1. 使用者問「找出標記為 'Important' 的文件標題」。
  2. 系統用 v1 prompt 生成的 SQL 把關聯表名寫成 `document_tags`（錯）；應為 `document_tags_mapping`。
  3. 執行失敗 → 寫入 attempts(failed)、failures(open)。
  4. Supervisor 提出 sql_patch candidate：把 SQL 改成正確的 `document_tags_mapping`。
  5. SqlSandbox 在 `sandbox_temp_*` schema 內：
       - setup：以 sandbox_runner 身份在 temp schema 內建 `documents` + `document_tags_mapping`
         並塞測試 seed（一篇被標 Important）；
       - replay：執行 candidate 的修正 SQL，驗證結果有一列、title 為 seed 標題。
  6. Gary 批准 → 套用 → 原任務重跑成功。

執行：
  KERNEL_DATABASE_URL=postgresql:///clk_test \\
  KERNEL_ALLOW_DESTRUCTIVE_RESET=1 \\
  python3 -m closed_loop_kernel.sql_demo
"""
from __future__ import annotations

import json
import os

from .engine import KernelEngine
from .sql_sandbox import SqlSandbox
from .store import RESET_CONFIRMATION, KernelStore


BROKEN_SQL = (
    "SELECT d.title FROM documents d "
    "JOIN document_tags t ON d.id = t.document_id "
    "WHERE t.tag_name = 'Important'"
)
FIXED_SQL = (
    "SELECT d.title FROM documents d "
    "JOIN document_tags_mapping t ON d.id = t.document_id "
    "WHERE t.tag_name = 'Important'"
)
REPLAY_SETUP_SQL = (
    "CREATE TABLE documents (id int PRIMARY KEY, title text NOT NULL); "
    "CREATE TABLE document_tags_mapping (document_id int, tag_name text, "
    "PRIMARY KEY (document_id, tag_name)); "
    "INSERT INTO documents VALUES (1, 'Q2 Strategy'), (2, 'Old Meeting Notes'); "
    "INSERT INTO document_tags_mapping VALUES (1, 'Important'), (2, 'Archive');"
)
EXPECTED_REPLAY_RESULT = [["Q2 Strategy"]]


def run_sql_demo() -> dict[str, object]:
    store = KernelStore.from_url(_database_url())
    try:
        _reset_demo_database(store)
        store.initialize()
        engine = KernelEngine(store)
        sandbox = SqlSandbox(_database_url(), runner_role="sandbox_runner")
        sandbox.ensure_role()

        artifact_id = engine.create_artifact(
            "text_to_sql.prompts.documents",
            "sql",
            BROKEN_SQL,
        )

        failed_attempt_id = engine.start_attempt(
            {"query": "找出標記為 Important 的文件標題"},
        )
        engine.finish_attempt(
            failed_attempt_id,
            "failed",
            {"query": "找出標記為 Important 的文件標題"},
            error_message='ERROR: relation "document_tags" does not exist',
            tool_calls=[
                {
                    "tool_name": "text_to_sql_executor",
                    "arguments": {"sql": BROKEN_SQL},
                    "status": "failed",
                    "error_message": 'ERROR: relation "document_tags" does not exist',
                }
            ],
        )
        failure_id = store.scalar(
            "SELECT id FROM failures WHERE attempt_id = ?",
            [failed_attempt_id],
        )

        candidate_id = engine.propose_improvement(
            failure_id,
            target_artifact_id=artifact_id,
            patch_type="sql_patch",
            proposed_content=FIXED_SQL,
            validation_assertions={
                "expected_row_count": 1,
                "expected_result": EXPECTED_REPLAY_RESULT,
            },
            rollback_plan={"restore_artifact_id": artifact_id},
        )

        engine.replay_sql_candidate(
            candidate_id,
            sandbox,
            setup_sql=REPLAY_SETUP_SQL,
        )
        engine.approve_candidate(candidate_id, "human_dri:gary", "Scenario 1 demo approval")
        engine.apply_candidate(candidate_id)

        # 部署後重跑原任務：模擬使用新版 prompt 產生 FIXED_SQL 並執行成功
        retry_attempt_id = engine.start_attempt(
            {"query": "找出標記為 Important 的文件標題（retry）"},
        )
        engine.finish_attempt(
            retry_attempt_id,
            "success",
            {"query": "找出標記為 Important 的文件標題（retry）"},
            output_payload={"rows": EXPECTED_REPLAY_RESULT},
            tool_calls=[
                {
                    "tool_name": "text_to_sql_executor",
                    "arguments": {"sql": FIXED_SQL},
                    "result": EXPECTED_REPLAY_RESULT,
                    "status": "success",
                }
            ],
        )

        return {
            "failed_attempt_id": failed_attempt_id,
            "retry_attempt_id": retry_attempt_id,
            "candidate_id": candidate_id,
            "failure_status": store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]),
            "candidate_status": store.scalar(
                "SELECT status FROM improvement_candidates WHERE id = ?",
                [candidate_id],
            ),
            "replay_status": store.scalar(
                "SELECT status FROM replays WHERE candidate_id = ?",
                [candidate_id],
            ),
            "replay_sandbox_schema": store.scalar(
                "SELECT sandbox_schema FROM replays WHERE candidate_id = ?",
                [candidate_id],
            ),
            "active_artifact_content": store.scalar(
                "SELECT content FROM artifacts WHERE name = ? AND is_active = TRUE",
                ["text_to_sql.prompts.documents"],
            ),
            "attempt_history": [
                {"id": row["id"], "status": row["status"], "error_message": row["error_message"]}
                for row in store.fetch_all(
                    "SELECT id, status, error_message FROM attempts "
                    "WHERE id IN (?, ?) ORDER BY created_at",
                    [failed_attempt_id, retry_attempt_id],
                )
            ],
        }
    finally:
        store.close()


def _database_url() -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise RuntimeError("KERNEL_DATABASE_URL is required; kernel runtime is PostgreSQL-only")
    return url


def _reset_demo_database(store: KernelStore) -> None:
    if os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET") != "1":
        raise RuntimeError("KERNEL_ALLOW_DESTRUCTIVE_RESET=1 is required to reset the PostgreSQL demo database")
    store.reset_for_test(confirm=RESET_CONFIRMATION)


if __name__ == "__main__":
    print(json.dumps(run_sql_demo(), ensure_ascii=False, indent=2, sort_keys=True))
