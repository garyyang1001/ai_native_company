"""V0.3 Phase 8 (simple) — apply + kill candidate tests."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("KERNEL_DATABASE_URL", "postgresql://test:test@localhost/none")


def _load_apply():
    path = Path(REPO) / "scripts" / "op_assistant" / "op_assistant_apply_canary.py"
    spec = importlib.util.spec_from_file_location("op_apply_canary_mod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ac = _load_apply()


class FakeTxn:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store

    def execute(self, sql, params=None) -> None:
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "UPDATE improvement_candidates SET status = 'applied'" in sql_norm:
            cid = params_list[0]
            if self._store.candidates.get(cid, {}).get("status") == "patch_emitted":
                self._store.candidates[cid]["status"] = "applied"
        elif "UPDATE improvement_candidates SET status = 'killed'" in sql_norm:
            cid = params_list[0]
            if cid in self._store.candidates:
                self._store.candidates[cid]["status"] = "killed"
        elif "INSERT INTO events" in sql_norm:
            self._store.events.append({
                "id": params_list[0],
                "event_type": params_list[1],
                "payload": params_list[2],
                "created_at": params_list[3],
            })


class FakeStore:
    def __init__(self) -> None:
        self.candidates: dict[str, dict] = {}
        self.events: list[dict] = []
        self.events_payload_lookup: dict[str, dict] = {}

    def fetch_one(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "FROM improvement_candidates WHERE id" in sql_norm:
            return self.candidates.get(params_list[0])
        if "FROM events" in sql_norm and "event_type = 'candidate_status_changed'" in sql_norm:
            cid = params_list[0]
            return self.events_payload_lookup.get(cid)
        return None

    @contextmanager
    def transaction(self):
        yield FakeTxn(self)


CID = "3f356f63-1a3e-539b-9478-a59dcb476611"


def _seed_patch_emitted(store: FakeStore, *, commit_sha="abc123") -> None:
    store.candidates[CID] = {
        "id": CID, "status": "patch_emitted",
        "proposal_type": "availability_keyword",
        "typed_payload": {"value": "沒有賣完"},
    }
    store.events_payload_lookup[CID] = {
        "payload": {
            "candidate_id": CID,
            "to_status": "patch_emitted",
            "commit_sha": commit_sha,
        },
    }


class ApplyCandidateTests(unittest.TestCase):
    def test_missing_returns_missing(self) -> None:
        out = ac.apply_candidate(FakeStore(), "nope", restart_service=False)
        self.assertEqual(out["status"], "missing")

    def test_wrong_state_when_draft(self) -> None:
        store = FakeStore()
        store.candidates[CID] = {
            "id": CID, "status": "draft",
            "proposal_type": "availability_keyword",
            "typed_payload": {"value": "x"},
        }
        out = ac.apply_candidate(store, CID, restart_service=False)
        self.assertEqual(out["status"], "wrong_state")
        self.assertEqual(out["candidate_status"], "draft")

    def test_happy_apply_no_restart(self) -> None:
        store = FakeStore()
        _seed_patch_emitted(store)
        out = ac.apply_candidate(store, CID, restart_service=False)
        self.assertEqual(out["status"], "applied")
        self.assertEqual(store.candidates[CID]["status"], "applied")
        events = [e for e in store.events if e["event_type"] == "candidate_status_changed"]
        self.assertEqual(len(events), 1)


class KillCandidateTests(unittest.TestCase):
    def test_missing_returns_missing(self) -> None:
        out = ac.kill_candidate(FakeStore(), "nope", restart_service=False)
        self.assertEqual(out["status"], "missing")

    def test_wrong_state_when_draft(self) -> None:
        store = FakeStore()
        store.candidates[CID] = {
            "id": CID, "status": "draft", "typed_payload": {"value": "x"},
        }
        out = ac.kill_candidate(store, CID, restart_service=False)
        self.assertEqual(out["status"], "wrong_state")

    def test_kill_from_applied_with_revert_mocked(self) -> None:
        store = FakeStore()
        _seed_patch_emitted(store)
        store.candidates[CID]["status"] = "applied"

        # Mock subprocess.run so git revert "succeeds"
        with patch.object(ac.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            out = ac.kill_candidate(
                store, CID, by_actor="999", reason="test",
                restart_service=False,
            )
        self.assertEqual(out["status"], "killed")
        self.assertEqual(store.candidates[CID]["status"], "killed")
        self.assertEqual(out["reverted_commit_sha"], "abc123")
        events = [e for e in store.events if e["event_type"] == "candidate_status_changed"]
        self.assertEqual(len(events), 1)

    def test_no_op_already_present_sha_does_not_attempt_revert(self) -> None:
        store = FakeStore()
        _seed_patch_emitted(store, commit_sha="(no-op-already-present)")
        store.candidates[CID]["status"] = "applied"
        with patch.object(ac.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 0
            out = ac.kill_candidate(
                store, CID, restart_service=False,
            )
        self.assertEqual(out["status"], "killed")
        # subprocess.run must not have been called for a git revert because
        # there is no real sha to revert.
        self.assertEqual(mock_run.call_count, 0)
        self.assertIsNone(out["reverted_commit_sha"])

    def test_missing_commit_event_returns_missing_commit_event(self) -> None:
        store = FakeStore()
        store.candidates[CID] = {
            "id": CID, "status": "applied", "typed_payload": {"value": "x"},
        }
        # No events_payload_lookup entry for CID
        out = ac.kill_candidate(store, CID, restart_service=False)
        self.assertEqual(out["status"], "missing_commit_event")


if __name__ == "__main__":
    unittest.main()
