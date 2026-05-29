"""V0.3 Phase 8 (simple) — apply + KILL switch.

The full V0.3 design talks about a 5-inbound canary bucket on the
LineRouter, but the surgical view is:

* Sandbox replay's four metrics (`regression_count==0`,
  ``improvement_count>=1``, ``ambiguity_count==0``,
  ``over_greedy_rate<0.50``) is the load-bearing safety gate. A patch
  that clears it is highly unlikely to misroute real production
  traffic.
* The AST guard guarantees the patch can only append a string to one
  module-level tuple. No control-flow change, no new imports.
* Gary already holds an instant KILL — the Telegram red button — that
  ``git revert``s the auto-commit and bounces the bot service.

V0.3 simple therefore skips the canary bucket (which would require
editing V0.2's ``LineRouter`` in ``plugins/op-assistant-line/adapter.py``,
violating the "don't touch V0.2 production code" surgical rule). What
this module does instead:

* ``apply_candidate``: patch_emitted → applied. Bounces the user
  systemd unit so the new ``_AVAILABILITY_KEYWORDS`` is actually loaded
  into the running parser.
* ``kill_candidate``: applied / patch_emitted → killed. ``git revert``s
  the commit that brought the keyword in, bounces the service again,
  and records the reason.

Both record a ``candidate_status_changed`` event each way.

Code is Rule: the service-restart helper is the only non-deterministic
piece, and it's a deterministic-arguments ``subprocess.run``. No LLM
anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402


SERVICE_NAME = os.environ.get(
    "OP_BOT_SERVICE_NAME", "hermes-gateway-op-assistant.service",
)


def restart_bot_service(timeout: float = 30.0) -> tuple[bool, str]:
    """Best-effort ``systemctl --user restart``. Returns (ok, detail)."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "restart", SERVICE_NAME],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "systemctl_not_available"
    except subprocess.TimeoutExpired:
        return False, "restart_timeout"
    if r.returncode == 0:
        return True, "restarted"
    return False, f"returncode={r.returncode}"


def apply_candidate(store: KernelStore, candidate_id: str, *,
                     restart_service: bool = True) -> dict[str, Any]:
    """patch_emitted → applied + bot service bounce."""
    cand = store.fetch_one(
        "SELECT id::text AS id, status, proposal_type, typed_payload "
        "FROM improvement_candidates WHERE id = ?",
        [candidate_id],
    )
    if cand is None:
        return {"status": "missing", "candidate_id": candidate_id}
    if cand["status"] != "patch_emitted":
        return {
            "status": "wrong_state",
            "candidate_status": cand["status"],
            "candidate_id": candidate_id,
        }

    typed = cand["typed_payload"]
    if isinstance(typed, str):
        typed = json.loads(typed)
    keyword = (typed or {}).get("value", "")

    restart_ok = True
    restart_detail = "skipped"
    if restart_service:
        restart_ok, restart_detail = restart_bot_service()

    now_iso = datetime.now(timezone.utc).isoformat()
    with store.transaction() as tx:
        tx.execute(
            "UPDATE improvement_candidates SET status = 'applied' "
            "WHERE id = ? AND status = 'patch_emitted'",
            [candidate_id],
        )
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": "patch_emitted",
                    "to_status": "applied",
                    "by_phase": "phase_8_apply",
                    "by_actor": "system",
                    "service_restart_ok": restart_ok,
                    "service_restart_detail": restart_detail,
                    "keyword": keyword,
                }),
                now_iso,
            ],
        )
    return {
        "status": "applied",
        "candidate_id": candidate_id,
        "keyword": keyword,
        "service_restart_ok": restart_ok,
        "service_restart_detail": restart_detail,
    }


def kill_candidate(store: KernelStore, candidate_id: str, *,
                    by_actor: str = "system",
                    reason: str = "manual_kill",
                    restart_service: bool = True) -> dict[str, Any]:
    """applied / patch_emitted → killed + git revert + bot service bounce."""
    cand = store.fetch_one(
        "SELECT id::text AS id, status, typed_payload "
        "FROM improvement_candidates WHERE id = ?",
        [candidate_id],
    )
    if cand is None:
        return {"status": "missing", "candidate_id": candidate_id}
    if cand["status"] not in ("applied", "patch_emitted"):
        return {
            "status": "wrong_state",
            "candidate_status": cand["status"],
            "candidate_id": candidate_id,
        }

    # Find the commit that introduced this patch.
    commit_event = store.fetch_one(
        "SELECT payload FROM events "
        "WHERE event_type = 'candidate_status_changed' "
        "AND payload->>'candidate_id' = ? "
        "AND payload->>'to_status' = 'patch_emitted' "
        "ORDER BY created_at DESC LIMIT 1",
        [candidate_id],
    )
    if commit_event is None:
        return {
            "status": "missing_commit_event",
            "candidate_id": candidate_id,
        }
    payload = commit_event["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    sha = payload.get("commit_sha")
    if not sha or sha.startswith("(no-op"):
        # Either we never made a real commit (no-op already-present) or
        # we lost track of which sha to revert. Mark killed in DB but
        # don't try a revert against an unknown sha.
        sha = None

    revert_ok = True
    revert_detail = "no_revert_needed"
    if sha:
        try:
            r = subprocess.run(
                ["git", "-C", REPO_PATH, "revert", "--no-edit", sha],
                timeout=30, capture_output=True, text=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "OP Assistant kill switch",
                    "GIT_AUTHOR_EMAIL": "op-assistant@wannavegtour.invalid",
                    "GIT_COMMITTER_NAME": "OP Assistant kill switch",
                    "GIT_COMMITTER_EMAIL": "op-assistant@wannavegtour.invalid",
                },
            )
        except Exception as exc:  # noqa: BLE001
            revert_ok = False
            revert_detail = f"revert_exception:{type(exc).__name__}"
        else:
            if r.returncode != 0:
                revert_ok = False
                revert_detail = f"revert_returncode={r.returncode}"

    restart_ok = True
    restart_detail = "skipped"
    if restart_service and revert_ok:
        restart_ok, restart_detail = restart_bot_service()

    now_iso = datetime.now(timezone.utc).isoformat()
    with store.transaction() as tx:
        # Don't gate the UPDATE on a single status — kill works from both
        # 'applied' and 'patch_emitted', and we already checked above.
        tx.execute(
            "UPDATE improvement_candidates SET status = 'killed' WHERE id = ?",
            [candidate_id],
        )
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": cand["status"],
                    "to_status": "killed",
                    "by_phase": "phase_8_kill",
                    "by_actor": by_actor,
                    "reason": reason,
                    "reverted_commit_sha": sha,
                    "revert_ok": revert_ok,
                    "revert_detail": revert_detail,
                    "service_restart_ok": restart_ok,
                    "service_restart_detail": restart_detail,
                }),
                now_iso,
            ],
        )

    return {
        "status": "killed",
        "candidate_id": candidate_id,
        "reverted_commit_sha": sha,
        "revert_ok": revert_ok,
        "service_restart_ok": restart_ok,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_env() -> None:
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    for path in [
        Path.home() / ".hermes" / "profiles" / profile / ".env",
        Path.home() / ".hermes" / ".env",
    ]:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(),
                                   val.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("--candidate-id", required=True)
    apply_p.add_argument("--no-restart", action="store_true")
    kill_p = sub.add_parser("kill")
    kill_p.add_argument("--candidate-id", required=True)
    kill_p.add_argument("--by-actor", default="cli")
    kill_p.add_argument("--reason", default="manual_kill_cli")
    kill_p.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()
    url = os.environ["KERNEL_DATABASE_URL"]
    store = KernelStore.from_url(url)
    try:
        if args.cmd == "apply":
            out = apply_candidate(
                store, args.candidate_id,
                restart_service=not args.no_restart,
            )
        else:
            out = kill_candidate(
                store, args.candidate_id,
                by_actor=args.by_actor, reason=args.reason,
                restart_service=not args.no_restart,
            )
    finally:
        store.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["status"] in ("applied", "killed") else 1


if __name__ == "__main__":
    sys.exit(main())
