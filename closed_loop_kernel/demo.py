from __future__ import annotations

import json

from .engine import KernelEngine
from .store import KernelStore


SAFE_PATCH = "def compute_score(base, bonus):\n    return base + (bonus or 0)\n"


def run_demo() -> dict[str, str | list[str]]:
    store = KernelStore.in_memory()
    store.initialize()
    engine = KernelEngine(store)

    artifact_id = engine.create_artifact(
        "skills.compute_score",
        "python",
        "def compute_score(base, bonus):\n    return base + bonus\n",
    )
    attempt_id = engine.start_attempt({"skill": "compute_score", "base": 10, "bonus": None})
    engine.finish_attempt(
        attempt_id,
        "failed",
        {"skill": "compute_score", "base": 10, "bonus": None},
        error_message="TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'",
        tool_calls=[
            {
                "tool_name": "skills.compute_score",
                "arguments": {"base": 10, "bonus": None},
                "status": "failed",
                "error_message": "TypeError",
            }
        ],
        decisions=[
            {
                "decision_maker": "policy_engine",
                "action_taken": "allowed",
                "reason": "local skill execution is allowed in prototype",
            }
        ],
    )
    failure_id = store.scalar("SELECT id FROM failures WHERE attempt_id = ?", [attempt_id])

    candidate_id = engine.propose_improvement(
        failure_id,
        target_artifact_id=artifact_id,
        patch_type="code_patch",
        proposed_content=SAFE_PATCH,
        validation_assertions={"unit": "compute_score_handles_none_bonus", "expected_result": 10},
        rollback_plan={"restore_artifact_id": artifact_id},
    )
    engine.replay_code_candidate(candidate_id, function_name="compute_score", args=[10, None])
    engine.approve_candidate(candidate_id, "human_dri:gary", "Demo replay passed")
    engine.apply_candidate(candidate_id)

    return {
        "attempt_id": attempt_id,
        "failed_attempt_status": store.scalar("SELECT status FROM attempts WHERE id = ?", [attempt_id]),
        "candidate_status": store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]),
        "failure_status": store.scalar("SELECT status FROM failures WHERE id = ?", [failure_id]),
        "active_artifact_content": store.scalar(
            "SELECT content FROM artifacts WHERE name = ? AND is_active = 1",
            ["skills.compute_score"],
        ),
        "blocked_terms": _blocked_terms(store),
    }


def _blocked_terms(store: KernelStore) -> list[str]:
    terms = ["100%", "水密級", "完全收斂", "符合度", "ALL PASS"]
    rows = []
    for table in ["events", "attempts", "failures", "improvement_candidates", "replays", "approvals"]:
        rows.extend(store.fetch_all(f"SELECT * FROM {table}"))
    blob = json.dumps(rows, ensure_ascii=False)
    return [term for term in terms if term in blob]


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2, sort_keys=True))
