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

from .store import KernelStore, json_param


APPROVAL_REQUIRED_EVENT = "approval_required"


# failure_type → (建議修正方向 template, proposed_content prefix)
_FAILURE_TEMPLATES: dict[str, dict[str, str]] = {
    "crash": {
        "summary": "agent 崩潰，建議在 system prompt 加入錯誤捕獲指示",
        "patch_template": (
            "（mock-LLM 第一版建議）\n"
            "在這個 agent 的 system prompt 末尾加入下列段落：\n\n"
            "  「遇到外部 API 連線錯誤（ConnectionError / RemoteDisconnected）時，\n"
            "  先 sleep 5 秒再重試一次。仍然失敗就回報詳細錯誤，不要直接崩潰。」\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "timeout": {
        "summary": "agent 執行超時，建議調整超時策略 / 拆分任務",
        "patch_template": (
            "（mock-LLM 第一版建議）\n"
            "在這個 agent 的 system prompt 加入：\n\n"
            "  「單次工具呼叫若超過 30 秒應主動回報『需要更多時間』而不是讓 worker timeout。\n"
            "  大型批次處理改成 chunk by chunk 並回報進度。」\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "spawn_failed": {
        "summary": "agent 啟動失敗，建議檢查 profile 設定",
        "patch_template": (
            "（mock-LLM 第一版建議）\n"
            "agent profile 啟動失敗，可能原因：\n"
            "  1. profile 資料夾缺少 SOUL.md\n"
            "  2. credentials 路徑指向不存在的檔案\n"
            "  3. venv 沒裝對應 Python 套件\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "gave_up": {
        "summary": "agent 重試多次後放棄，建議降級策略或人工介入",
        "patch_template": (
            "（mock-LLM 第一版建議）\n"
            "這個任務在連續多次失敗後被放棄。建議：\n"
            "  - 降低 retry 上限避免浪費資源\n"
            "  - 把這類失敗類型加入「直接派給人類」清單\n\n"
            "依據失敗 context：{error}"
        ),
    },
    "failed": {
        "summary": "agent 任務失敗（一般錯誤），建議分析 root cause",
        "patch_template": (
            "（mock-LLM 第一版建議）\n"
            "這個 agent 任務失敗，但錯誤類別不明確。建議：\n"
            "  - 為這個 agent 增加結構化錯誤回報\n"
            "  - 在 system prompt 加入「任何例外都要先輸出 1 行 root_cause: 摘要 再 raise」\n\n"
            "依據失敗 context：{error}"
        ),
    },
}

DEFAULT_TARGET_ARTIFACT_NAME = "ohya.agent_profiles.system_prompt"


class FailureAnalyzer:
    def __init__(
        self,
        store: KernelStore,
        target_artifact_name: str = DEFAULT_TARGET_ARTIFACT_NAME,
        artifact_type: str = "prompt",
    ):
        self.store = store
        self.target_artifact_name = target_artifact_name
        self.artifact_type = artifact_type

    def analyze_open_failures(self) -> dict[str, Any]:
        """
        掃 open 狀態 failures，產 candidate + event。
        回傳：{processed: N, skipped: M, candidates: [...]}
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
        target_artifact = self._ensure_target_artifact()
        for row in rows:
            try:
                candidate_id = self._propose_for_failure(row, target_artifact)
                self._record_approval_required(candidate_id, row["id"])
                candidates.append(candidate_id)
                processed += 1
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
        return {"processed": processed, "skipped": skipped, "candidates": candidates}

    def _ensure_target_artifact(self) -> dict:
        existing = self.store.fetch_one(
            "SELECT id, content, content_hash, version FROM artifacts WHERE name = ? AND is_active = TRUE",
            [self.target_artifact_name],
        )
        if existing:
            return existing
        # Seed 一個 placeholder artifact
        team_row = self.store.fetch_one("SELECT id FROM teams WHERE name = 'ohya'")
        team_id = team_row["id"] if team_row else None
        artifact_id = str(uuid.uuid4())
        placeholder = (
            "# OHYA agent system prompt (placeholder)\n\n"
            "這是一個 placeholder 用來讓 FailureAnalyzer 有目標可以提修正案。\n"
            "實際 agent prompt 改造階段會把這裡換成從 HermesRuntime/clients/ohya/profiles/{agent}/SOUL.md 讀的內容。\n"
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
        ctx = _parse_json(failure["context"])
        error_excerpt = (ctx.get("error") or failure.get("error_message") or "(no error message)")[:300]
        proposed_content = template["patch_template"].format(error=error_excerpt)
        validation_assertions = {
            "summary": template["summary"],
            "source_failure_type": failure_type,
            "tenant": ctx.get("tenant"),
        }
        rollback_plan = {
            "restore_artifact_id": target_artifact["id"],
            "note": "改回 placeholder prompt（demo 階段沒有實際歷史版本）",
        }
        candidate_id = str(uuid.uuid4())
        self.store.execute(
            """
            INSERT INTO improvement_candidates (
                id, failure_id, target_artifact_id, target_artifact_name, target_artifact_type,
                target_artifact_version, base_artifact_hash, patch_type, proposed_content,
                validation_assertions, rollback_plan, status, proposed_by_agent_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'prompt_update', ?, ?, ?, 'sandbox_verified', ?, ?)
            """,
            [
                candidate_id,
                failure["id"],
                target_artifact["id"],
                self.target_artifact_name,
                self.artifact_type,
                target_artifact["version"],
                target_artifact["content_hash"],
                proposed_content,
                json_param(validation_assertions),
                json_param(rollback_plan),
                failure.get("detected_by_agent_id"),
                _now(),
            ],
        )
        # mock sandbox replay：直接寫 success replay 讓 candidate 過 4 道部署校驗的「replay success」這一道
        self.store.execute(
            """
            INSERT INTO replays (id, candidate_id, status, validation_results, sandbox_env, created_at)
            VALUES (?, ?, 'success', ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                candidate_id,
                json_param({"mock": True, "note": "FailureAnalyzer 第一版用 mock 通過 sandbox replay"}),
                json_param({"sandbox_type": "mock-prompt-lint"}),
                _now(),
            ],
        )
        self.store.execute("UPDATE failures SET status = 'proposed' WHERE id = ?", [failure["id"]])
        return candidate_id

    def _record_approval_required(self, candidate_id: str, failure_id: str) -> None:
        self.store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                APPROVAL_REQUIRED_EVENT,
                json_param({"candidate_id": candidate_id, "failure_id": failure_id, "source": "failure_analyzer"}),
                _now(),
            ],
        )


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
