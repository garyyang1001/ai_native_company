"""
FailureAnalyzer — 把 ohya_kernel 裡 open 狀態的 failures 轉成 improvement_candidates。

這是「Prompt 自癒閉環」的中介層。第一版用 hardcoded template（mock LLM），
之後可以接真實 LLM analysis。

流程：
  1. 找 failures.status='open' 且還沒對應 candidate 的
  2. 根據 failure_type 套用對應模板（crash / timeout / spawn_failed 等）
  3. 確保有 target artifact (placeholder 也行)，建 improvement_candidate
  4. raise `approval_required` event 給 ohya_approval_bot 看到後推 Telegram

為什麼第一版不真接 LLM：
  Telegram 推送 + approvals 表寫回的完整鏈路要先驗證；LLM analysis
  可以後續直接替換 _analyze() 即可（介面已隔離）。
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .engine import KernelEngine
from .store import KernelStore, json_param


APPROVAL_REQUIRED_EVENT = "approval_required"

# 第一輪：crash failure 對應的 code_patch test function 名稱（FailureAnalyzer 寫進 candidate
# 的 patch_template 內含這個 function，sandbox replay 跑它即可驗證 retry 行為）。
_SANDBOX_TEST_FUNCTION = {
    "crash": "test_retry_recovers_on_third_attempt",
}


# failure_type → 修正策略
#
# 依 spec/code-is-law-v0.md 第 4 節：所有 control-flow 失敗（crash / timeout /
# spawn_failed / gave_up / failed）的第一選擇都是 `code_patch`，不是 `prompt_update`。
# 模板給出明確的程式碼修法方向，FailureAnalyzer 把它包成 candidate 給 sandbox replay。
_FAILURE_TEMPLATES: dict[str, dict[str, str]] = {
    "crash": {
        "summary": "agent 程式碼崩潰；改成依賴注入版 + exponential backoff retry，sandbox 可真實跑 test",
        "patch_type": "code_patch",
        "target_hint": "ohya.cms_draft_executor.http_client",
        "patch_template": (
            "# code_patch 提議（mock-LLM 第一版；正式版接真實 LLM 後會由 LLM 讀真實程式碼產出）\n"
            "#\n"
            "# 設計原則：\n"
            "#   1. 純函式：http_call 由外部注入，sandbox 可以 mock 進去測 retry 行為\n"
            "#   2. retry 走 exponential backoff（2^attempt 秒，但 sandbox 用 BASE_WAIT_SECONDS=0.01 加速）\n"
            "#   3. 最終失敗 reraise 原始例外，讓上層完整看到 root cause\n"
            "#\n"
            "# 依據失敗 context：{error}\n"
            "\n"
            "import time\n"
            "\n"
            "MAX_RETRIES = 5\n"
            "BASE_WAIT_SECONDS = 0.01  # sandbox 跑 test 用；production 會被注入成 2.0\n"
            "\n"
            "\n"
            "class TransientError(Exception):\n"
            "    pass\n"
            "\n"
            "\n"
            "def publish_draft(http_call, payload):\n"
            "    last_exc = None\n"
            "    for attempt in range(MAX_RETRIES):\n"
            "        try:\n"
            "            return http_call(payload)\n"
            "        except TransientError as exc:\n"
            "            last_exc = exc\n"
            "            if attempt < MAX_RETRIES - 1:\n"
            "                time.sleep(BASE_WAIT_SECONDS * (2 ** attempt))\n"
            "    raise last_exc\n"
            "\n"
            "\n"
            "def test_retry_recovers_on_third_attempt():\n"
            "    \"\"\"sandbox 跑這個來證明 retry 行為正確；連 2 次 TransientError 後第 3 次成功。\"\"\"\n"
            "    call_log = []\n"
            "    def fake_http(payload):\n"
            "        call_log.append(dict(payload))\n"
            "        if len(call_log) < 3:\n"
            "            raise TransientError('attempt ' + str(len(call_log)) + ' failed')\n"
            "        return {'post_id': payload.get('id'), 'status': 'published'}\n"
            "    result = publish_draft(fake_http, {'id': 4751})\n"
            "    assert len(call_log) == 3, 'expected 3 attempts, got ' + str(len(call_log))\n"
            "    assert result == {'post_id': 4751, 'status': 'published'}\n"
            "    return {'ok': True, 'attempts_taken': 3, 'final_result': result}\n"
            "\n"
            "\n"
            "def test_gives_up_after_max_retries():\n"
            "    \"\"\"連續 MAX_RETRIES 次都失敗應該 raise 最後一次的例外。\"\"\"\n"
            "    call_count = [0]\n"
            "    def always_fails(payload):\n"
            "        call_count[0] += 1\n"
            "        raise TransientError('persistent failure #' + str(call_count[0]))\n"
            "    raised = None\n"
            "    try:\n"
            "        publish_draft(always_fails, {'id': 9999})\n"
            "    except TransientError as exc:\n"
            "        raised = str(exc)\n"
            "    assert call_count[0] == MAX_RETRIES, 'expected ' + str(MAX_RETRIES) + ' attempts, got ' + str(call_count[0])\n"
            "    assert raised is not None and 'persistent failure' in raised\n"
            "    return {'ok': True, 'attempts_taken': MAX_RETRIES, 'final_exception': raised}\n"
        ),
    },
    "timeout": {
        "summary": "agent worker 超時，建議調 HTTP timeout 配置與切批次大小",
        "patch_type": "code_patch",
        "target_hint": "agent 的 HTTP client 設定或 batch processor 程式碼",
        "patch_template": (
            "（mock-LLM 第一版建議；正式版要由 LLM 讀真實程式碼後產出）\n\n"
            "修改方向（code_patch）：\n"
            "  1. requests timeout 從預設值改成 (connect=10, read=180) — 雲端服務 cold start 可能需要 1-2 分鐘\n"
            "  2. 大型 batch（>= 50 items）拆成 chunk_size=10 的子批次處理，每個 chunk 之間 yield 一次 progress\n"
            "  3. worker max_runtime_seconds 從預設 60 提到 600（kanban tasks 欄位已有此設定）\n\n"
            "sandbox replay 應該驗證：mock slow response (3 秒) × 10 個 items 應該全部完成，不能 timeout。\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "spawn_failed": {
        "summary": "agent 進程啟動失敗，建議自動修 profile 完整性",
        "patch_type": "code_patch",
        "target_hint": "hermes-agent 的 profile loader 或 launchctl plist generator",
        "patch_template": (
            "（mock-LLM 第一版建議）\n\n"
            "修改方向（code_patch）：在 profile loader 加 pre-flight check，啟動前先驗證：\n"
            "  1. profile 資料夾存在且含 SOUL.md\n"
            "  2. credentials/ 內所有 *.json 都是有效 JSON 且必要 key 都有\n"
            "  3. venv 的 python -m hermes_cli.main --version 能跑出版本號\n"
            "缺哪一項就 raise 明確錯誤而不是讓 spawn 半路死掉。\n\n"
            "sandbox replay 應該驗證：故意刪掉 SOUL.md，pre-flight check 必須 raise SoulMdMissing 例外。\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "gave_up": {
        "summary": "agent 連續失敗達上限後放棄，建議改 escalation 機制",
        "patch_type": "code_patch",
        "target_hint": "hermes-agent worker 的 give-up handler",
        "patch_template": (
            "（mock-LLM 第一版建議）\n\n"
            "修改方向（code_patch）：在 give-up 流程加 escalation hook，自動：\n"
            "  1. 把 task 標 status='blocked' + reason='exhausted_retries'\n"
            "  2. 寫一筆 task_event(kind='escalated_to_human', payload={'failure_count': N})\n"
            "  3. （配合 ohya_kernel）raise approval_required event 推 Telegram 給 DRI\n"
            "max_retries 數值留在 config（不在程式碼裡 hard code），方便 DRI 個案調整。\n\n"
            "sandbox replay 應該驗證：模擬 5 次連續失敗後第 6 次 give-up，必須產出對應 events 並推 escalation。\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "failed": {
        "summary": "agent 任務一般失敗，建議補結構化錯誤回報層",
        "patch_type": "code_patch",
        "target_hint": "agent 的 error handler / tool_call wrapper",
        "patch_template": (
            "（mock-LLM 第一版建議）\n\n"
            "修改方向（code_patch）：把 agent 的 tool_call wrapper 統一加結構化錯誤處理：\n\n"
            "  def wrap_tool_call(tool_name, fn, *args, **kwargs):\n"
            "      try:\n"
            "          result = fn(*args, **kwargs)\n"
            "          return {'status': 'success', 'result': result}\n"
            "      except Exception as exc:\n"
            "          return {\n"
            "              'status': 'failed',\n"
            "              'error_type': type(exc).__name__,\n"
            "              'error_message': str(exc),\n"
            "              'root_cause_hint': _classify(exc),  # network / auth / quota / data\n"
            "          }\n\n"
            "sandbox replay 應該驗證：丟 ConnectionError / AuthError / 一般 ValueError 進去，回傳的 root_cause_hint 必須分別是 network / auth / 'unknown'。\n\n"
            "依據失敗 context：{error}"
        ),
    },
}

DEFAULT_TARGET_ARTIFACT_NAME = "ohya.cms_draft_executor.http_client"
DEFAULT_TARGET_ARTIFACT_TYPE = "python"


class FailureAnalyzer:
    def __init__(
        self,
        store: KernelStore,
        target_artifact_name: str = DEFAULT_TARGET_ARTIFACT_NAME,
        artifact_type: str = DEFAULT_TARGET_ARTIFACT_TYPE,
    ):
        self.store = store
        self.target_artifact_name = target_artifact_name
        self.artifact_type = artifact_type

    def analyze_open_failures(self, run_sandbox: bool = True) -> dict[str, Any]:
        """
        對 open failures 做：
          1. 提 candidate（draft 狀態）
          2. (預設) 真實 sandbox replay candidate 的 code_patch test
          3. sandbox 通過 → candidate→sandbox_verified + raise approval_required（由 engine.record_replay 自動處理）

        傳 run_sandbox=False 可以只提 candidate 不跑 sandbox（單元測試 / 不想動 sandbox 時用）。
        回傳：{processed, skipped, candidates, sandbox_passed, sandbox_failed}
        """
        rows = self.store.fetch_all(
            """
            SELECT f.id, f.attempt_id, f.failure_type, f.context, f.detected_by_agent_id,
                   a.error_message
            FROM failures f
            LEFT JOIN attempts a ON a.id = f.attempt_id
            WHERE f.status = 'open'
              AND NOT EXISTS (
                  SELECT 1 FROM improvement_candidates c WHERE c.failure_id = f.id
              )
            ORDER BY f.created_at ASC
            """
        )
        processed = 0
        skipped = 0
        candidates: list[str] = []
        sandbox_passed = 0
        sandbox_failed = 0
        target_artifact = self._ensure_target_artifact()
        engine = KernelEngine(self.store)
        for row in rows:
            try:
                candidate_id = self._propose_for_failure(row, target_artifact)
                candidates.append(candidate_id)
                processed += 1
                if run_sandbox:
                    test_fn = _SANDBOX_TEST_FUNCTION.get(row["failure_type"])
                    if test_fn:
                        engine.replay_code_candidate(candidate_id, function_name=test_fn, args=[])
                        new_status = self.store.scalar(
                            "SELECT status FROM improvement_candidates WHERE id = ?",
                            [candidate_id],
                        )
                        if new_status == "sandbox_verified":
                            sandbox_passed += 1
                        else:
                            sandbox_failed += 1
            except Exception as exc:
                skipped += 1
                self.store.execute(
                    "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                    [
                        str(uuid.uuid4()),
                        "ohya_analyzer_skip",
                        json_param({"failure_id": row["id"], "error": str(exc)}),
                        _now(),
                    ],
                )
        return {
            "processed": processed,
            "skipped": skipped,
            "candidates": candidates,
            "sandbox_passed": sandbox_passed,
            "sandbox_failed": sandbox_failed,
        }

    def _ensure_target_artifact(self) -> dict:
        existing = self.store.fetch_one(
            "SELECT id, content, content_hash, version FROM artifacts WHERE name = ? AND is_active = TRUE",
            [self.target_artifact_name],
        )
        if existing:
            return existing
        # Seed 一個 placeholder code artifact（之後會被 LLM 提的 code_patch 取代）
        team_row = self.store.fetch_one("SELECT id FROM teams WHERE name = 'ohya'")
        team_id = team_row["id"] if team_row else None
        artifact_id = str(uuid.uuid4())
        # placeholder 寫成「裸 HTTP call」— 故意有缺陷，等改進
        placeholder = (
            "# OHYA cms-draft-executor HTTP client (v1, placeholder — 故意留缺陷待 LLM 改進)\n"
            "import requests\n\n\n"
            "def publish_draft(payload: dict) -> dict:\n"
            "    # ⚠️ 沒 retry / 沒 timeout / 沒結構化錯誤回報 — 失敗就 raise ConnectionError\n"
            "    resp = requests.post('https://payload.ohya.co/api/posts', json=payload)\n"
            "    resp.raise_for_status()\n"
            "    return resp.json()\n"
        )
        content_hash = hashlib.sha256(placeholder.encode("utf-8")).hexdigest()
        self.store.execute(
            """
            INSERT INTO artifacts (id, name, artifact_type, content, content_hash, version, is_active, owner_team_id, created_at)
            VALUES (?, ?, ?, ?, ?, 1, TRUE, ?, ?)
            """,
            [artifact_id, self.target_artifact_name, self.artifact_type, placeholder, content_hash, team_id, _now()],
        )
        return {"id": artifact_id, "content": placeholder, "content_hash": content_hash, "version": 1}

    def _propose_for_failure(self, failure: dict, target_artifact: dict) -> str:
        failure_type = failure["failure_type"]
        template = _FAILURE_TEMPLATES.get(failure_type) or _FAILURE_TEMPLATES["failed"]
        patch_type = template["patch_type"]  # 依 spec/code-is-law-v0.md 第 4 節，主力是 code_patch
        ctx = _parse_json(failure["context"])
        error_excerpt = (ctx.get("error") or failure.get("error_message") or "(no error message)")[:300]
        proposed_content = template["patch_template"].format(error=error_excerpt)
        validation_assertions = {
            "summary": template["summary"],
            "source_failure_type": failure_type,
            "target_hint": template["target_hint"],
            "tenant": ctx.get("tenant"),
        }
        rollback_plan = {
            "restore_artifact_id": target_artifact["id"],
            "note": "rollback 到 placeholder artifact 版本",
        }
        candidate_id = str(uuid.uuid4())
        # 注意：這裡 status 暫時設 'draft'，由後續 sandbox replay 把它推到 'sandbox_verified'。
        # 違反 Code is Law 的第一版（直接寫 sandbox_verified + mock success replay）已經移除。
        self.store.execute(
            """
            INSERT INTO improvement_candidates (
                id, failure_id, target_artifact_id, target_artifact_name, target_artifact_type,
                target_artifact_version, base_artifact_hash, patch_type, proposed_content,
                validation_assertions, rollback_plan, status, proposed_by_agent_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            [
                candidate_id,
                failure["id"],
                target_artifact["id"],
                self.target_artifact_name,
                self.artifact_type,
                target_artifact["version"],
                target_artifact["content_hash"],
                patch_type,
                proposed_content,
                json_param(validation_assertions),
                json_param(rollback_plan),
                failure.get("detected_by_agent_id"),
                _now(),
            ],
        )
        self.store.execute("UPDATE failures SET status = 'proposed' WHERE id = ?", [failure["id"]])
        return candidate_id

def _parse_json(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("KERNEL_DATABASE_URL"))
    args = parser.parse_args()
    if not args.url:
        raise SystemExit("KERNEL_DATABASE_URL is required")
    store = KernelStore.from_url(args.url)
    try:
        analyzer = FailureAnalyzer(store)
        result = analyzer.analyze_open_failures()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        store.close()
