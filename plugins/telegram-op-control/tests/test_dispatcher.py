"""V0.3 Phase 4 dispatcher — parse + claim_and_apply + dispatch_callback.

FakeStore stands in for KernelStore so we don't need a live PostgreSQL
connection. The dispatcher logic is pure deterministic Python; the only
external moving piece (sandbox replay) is monkey-patched in the
``DispatchCallbackIntegrationTests`` class.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("KERNEL_DATABASE_URL", "postgresql://test:test@localhost/none")


def _load_dispatcher():
    path = Path(REPO) / "plugins" / "telegram-op-control" / "dispatcher.py"
    spec = importlib.util.spec_from_file_location("phase4_dispatcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase4_dispatcher"] = module
    spec.loader.exec_module(module)
    return module


dp = _load_dispatcher()


# ---------------------------------------------------------------------
# FakeStore — emulates KernelStore.transaction() / fetch_one / execute
# ---------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeTxn:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store
        self.calls: list[tuple[str, list[Any]]] = []

    def execute(self, sql: str, params=None) -> _FakeCursor:
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        self.calls.append((sql_norm, params_list))
        # Side effect emulation
        if "SELECT status FROM improvement_candidates" in sql_norm:
            cid = params_list[0]
            cand = self._store.candidates.get(cid)
            if cand is None:
                return _FakeCursor(None)
            return _FakeCursor({"status": cand["status"]})
        if "INSERT INTO approvals" in sql_norm and "ON CONFLICT" in sql_norm:
            source_event_id = params_list[4]
            if source_event_id in self._store.seen_source_event_ids:
                return _FakeCursor(None)
            self._store.seen_source_event_ids.add(source_event_id)
            self._store.approvals.append(dict(zip(
                ["id", "candidate_id", "approved_by", "decision",
                 "source_event_id", "channel_message_id",
                 "reject_reason", "created_at"],
                params_list,
            )))
            return _FakeCursor({"id": params_list[0]})
        if "UPDATE improvement_candidates SET status" in sql_norm:
            cid = params_list[1]
            if cid in self._store.candidates:
                self._store.candidates[cid]["status"] = params_list[0]
            return _FakeCursor(None)
        if "INSERT INTO events" in sql_norm:
            self._store.events.append({
                "id": params_list[0],
                "event_type": params_list[1],
                "payload": params_list[2],
                "created_at": params_list[3],
            })
            return _FakeCursor(None)
        return _FakeCursor(None)


class FakeStore:
    def __init__(self) -> None:
        self.candidates: dict[str, dict[str, Any]] = {}
        self.approvals: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.seen_source_event_ids: set[str] = set()
        self._executes: list[tuple[str, list[Any]]] = []

    @contextmanager
    def transaction(self):
        tx = _FakeTxn(self)
        try:
            yield tx
        except Exception:
            # Don't actually mutate — emulate rollback by discarding tx.calls
            raise
        # FakeTxn already mutated store state per call; in real PG, the
        # transaction commits here. Nothing to do; this is a simple fake.

    def execute(self, sql: str, params=None) -> None:
        # For non-transactional helpers (events writes via dispatcher's
        # error / unsupported paths).
        sql_norm = " ".join(sql.split())
        self._executes.append((sql_norm, list(params or [])))
        if "INSERT INTO events" in sql_norm:
            params_list = list(params or [])
            self.events.append({
                "id": params_list[0],
                "event_type": params_list[1],
                "payload": params_list[2],
                "created_at": params_list[3],
            })

    def fetch_one(self, sql: str, params=None) -> dict[str, Any] | None:
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "FROM improvement_candidates WHERE id" in sql_norm:
            return self.candidates.get(params_list[0])
        if "FROM sandbox_runs" in sql_norm:
            cid = params_list[0]
            for row in reversed(self.events):  # not actually sandbox_runs
                pass
            return getattr(self, "_latest_sandbox_run", None)


# ---------------------------------------------------------------------
# parse_callback_data + hex32_to_uuid
# ---------------------------------------------------------------------

class ParseCallbackDataTests(unittest.TestCase):
    def test_apv(self) -> None:
        self.assertEqual(
            dp.parse_callback_data("apv:3f356f631a3e539b9478a59dcb476611"),
            ("apv", "3f356f631a3e539b9478a59dcb476611"),
        )

    def test_rej(self) -> None:
        self.assertEqual(
            dp.parse_callback_data("rej:1299448be68e5df8a0197f848f32d6d2"),
            ("rej", "1299448be68e5df8a0197f848f32d6d2"),
        )

    def test_vw(self) -> None:
        self.assertEqual(
            dp.parse_callback_data("vw:3f356f631a3e539b9478a59dcb476611"),
            ("vw", "3f356f631a3e539b9478a59dcb476611"),
        )

    def test_kill(self) -> None:
        self.assertEqual(
            dp.parse_callback_data("kill:3f356f631a3e539b9478a59dcb476611"),
            ("kill", "3f356f631a3e539b9478a59dcb476611"),
        )

    def test_killall(self) -> None:
        self.assertEqual(
            dp.parse_callback_data("killall:e022a3b562cc580eb3bd8d2f02a38e14"),
            ("killall", "e022a3b562cc580eb3bd8d2f02a38e14"),
        )

    def test_short_id_rejected(self) -> None:
        # 8-hex is what the original draft tried; v0 contract requires 32.
        self.assertIsNone(dp.parse_callback_data("apv:3f356f63"))

    def test_uppercase_rejected(self) -> None:
        self.assertIsNone(
            dp.parse_callback_data("APV:3f356f631a3e539b9478a59dcb476611"),
        )

    def test_unknown_action_rejected(self) -> None:
        self.assertIsNone(
            dp.parse_callback_data("foo:3f356f631a3e539b9478a59dcb476611"),
        )

    def test_missing_colon_rejected(self) -> None:
        self.assertIsNone(dp.parse_callback_data("apv3f356f63..."))

    def test_non_string_input(self) -> None:
        self.assertIsNone(dp.parse_callback_data(None))  # type: ignore[arg-type]


class Hex32ToUuidTests(unittest.TestCase):
    def test_inserts_dashes(self) -> None:
        self.assertEqual(
            dp.hex32_to_uuid("3f356f631a3e539b9478a59dcb476611"),
            "3f356f63-1a3e-539b-9478-a59dcb476611",
        )

    def test_roundtrip(self) -> None:
        u = "1299448b-e68e-5df8-a019-7f848f32d6d2"
        self.assertEqual(dp.hex32_to_uuid(u.replace("-", "")), u)


# ---------------------------------------------------------------------
# claim_and_apply
# ---------------------------------------------------------------------

class ClaimAndApplyTests(unittest.TestCase):
    CANDIDATE_ID = "3f356f63-1a3e-539b-9478-a59dcb476611"

    def _store_with_draft_candidate(self) -> FakeStore:
        store = FakeStore()
        store.candidates[self.CANDIDATE_ID] = {
            "id": self.CANDIDATE_ID,
            "status": "draft",
            "proposal_type": "availability_keyword",
            "typed_payload": {"type": "keyword", "value": "沒有賣完"},
        }
        return store

    def test_happy_approve(self) -> None:
        store = self._store_with_draft_candidate()
        result = dp.claim_and_apply(
            store,
            source_event_id="11111111-1111-1111-1111-111111111111",
            candidate_id=self.CANDIDATE_ID,
            decision="approved",
            approved_by="999",
            channel_message_id="cb-1",
        )
        self.assertEqual(result, dp.ClaimResult.OK)
        self.assertEqual(store.candidates[self.CANDIDATE_ID]["status"], "approved")
        self.assertEqual(len(store.approvals), 1)
        self.assertEqual(store.approvals[0]["decision"], "approved")
        # candidate_status_changed event
        change_events = [
            e for e in store.events
            if e["event_type"] == "candidate_status_changed"
        ]
        self.assertEqual(len(change_events), 1)

    def test_happy_reject(self) -> None:
        store = self._store_with_draft_candidate()
        result = dp.claim_and_apply(
            store,
            source_event_id="22222222-2222-2222-2222-222222222222",
            candidate_id=self.CANDIDATE_ID,
            decision="rejected",
            approved_by="999",
        )
        self.assertEqual(result, dp.ClaimResult.OK)
        self.assertEqual(store.candidates[self.CANDIDATE_ID]["status"], "rejected")

    def test_unknown_candidate(self) -> None:
        store = FakeStore()
        result = dp.claim_and_apply(
            store,
            source_event_id="33333333-3333-3333-3333-333333333333",
            candidate_id="00000000-0000-0000-0000-000000000000",
            decision="approved",
            approved_by="999",
        )
        self.assertEqual(result, dp.ClaimResult.UNKNOWN_CANDIDATE)
        self.assertEqual(store.approvals, [])

    def test_stale_writes_event_not_approval(self) -> None:
        store = self._store_with_draft_candidate()
        # Pretend it was already approved by a prior path
        store.candidates[self.CANDIDATE_ID]["status"] = "approved"
        result = dp.claim_and_apply(
            store,
            source_event_id="44444444-4444-4444-4444-444444444444",
            candidate_id=self.CANDIDATE_ID,
            decision="approved",
            approved_by="999",
        )
        self.assertEqual(result, dp.ClaimResult.STALE)
        self.assertEqual(store.approvals, [])
        stale_events = [
            e for e in store.events
            if e["event_type"] == "telegram_callback_stale"
        ]
        self.assertEqual(len(stale_events), 1)

    def test_already_claimed_idempotent(self) -> None:
        store = self._store_with_draft_candidate()
        source_event_id = "55555555-5555-5555-5555-555555555555"
        first = dp.claim_and_apply(
            store, source_event_id=source_event_id,
            candidate_id=self.CANDIDATE_ID, decision="approved",
            approved_by="999",
        )
        # Reset status manually so the FakeStore stale check doesn't fire
        # first; this is the rerun-same-event_id scenario where the second
        # dispatcher attempt should hit the source_event_id unique index.
        store.candidates[self.CANDIDATE_ID]["status"] = "draft"
        second = dp.claim_and_apply(
            store, source_event_id=source_event_id,
            candidate_id=self.CANDIDATE_ID, decision="approved",
            approved_by="999",
        )
        self.assertEqual(first, dp.ClaimResult.OK)
        self.assertEqual(second, dp.ClaimResult.ALREADY_CLAIMED)
        self.assertEqual(len(store.approvals), 1)

    def test_kill_requires_applied_status(self) -> None:
        store = self._store_with_draft_candidate()
        store.candidates[self.CANDIDATE_ID]["status"] = "applied"
        result = dp.claim_and_apply(
            store,
            source_event_id="66666666-6666-6666-6666-666666666666",
            candidate_id=self.CANDIDATE_ID,
            decision="killed",
            approved_by="999",
        )
        self.assertEqual(result, dp.ClaimResult.OK)
        self.assertEqual(store.candidates[self.CANDIDATE_ID]["status"], "killed")


# ---------------------------------------------------------------------
# dispatch_callback end-to-end (FakeStore + mocked trigger_sandbox_replay)
# ---------------------------------------------------------------------

class DispatchCallbackIntegrationTests(unittest.TestCase):
    CANDIDATE_ID = "3f356f63-1a3e-539b-9478-a59dcb476611"
    CANDIDATE_HEX = CANDIDATE_ID.replace("-", "")

    def _store(self) -> FakeStore:
        store = FakeStore()
        store.candidates[self.CANDIDATE_ID] = {
            "id": self.CANDIDATE_ID,
            "status": "draft",
            "proposal_type": "availability_keyword",
            "typed_payload": {"type": "keyword", "value": "沒有賣完"},
        }
        return store

    def _callback(self, data: str) -> dict[str, Any]:
        return {
            "id": "cb-test",
            "from": {"id": 999, "first_name": "Gary"},
            "message": {
                "message_id": 100,
                "chat": {"id": 123, "type": "private"},
            },
            "data": data,
        }

    def test_apv_writes_approval_and_triggers_sandbox(self) -> None:
        store = self._store()
        calls: list[str] = []

        def _fake_replay(store_arg, kernel_url, candidate_id):
            calls.append(candidate_id)
            return {
                "run_id": "fake-run",
                "status": "passed",
                "fail_reason": None,
                "metrics": {
                    "regression_count": 0, "improvement_count": 1,
                    "ambiguity_count": 0, "over_greedy_rate": 0.05,
                },
                "duration_ms": 0,
                "model_digest": "fake",
                "corpus_snapshot_hash": "fake",
                "candidate_status_before": "draft",
            }
        dp.trigger_sandbox_replay = _fake_replay  # type: ignore[assignment]

        result = dp.dispatch_callback(
            store=store,
            kernel_url="postgresql://test/none",
            source_event_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            callback_query=self._callback(f"apv:{self.CANDIDATE_HEX}"),
        )

        self.assertEqual(result["action"], "apv")
        self.assertEqual(result["claim"], "ok")
        self.assertIn("✅", result["reply_text"])
        self.assertEqual(calls, [self.CANDIDATE_ID])
        self.assertIn("sandbox", result["sandbox_followup"])

    def test_malformed_callback_audit_only(self) -> None:
        store = self._store()
        result = dp.dispatch_callback(
            store=store,
            kernel_url="postgresql://test/none",
            source_event_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            callback_query=self._callback("bogus:notvalid"),
        )
        self.assertEqual(result["action"], None)
        self.assertIn("沒看懂", result["reply_text"])
        malformed_events = [
            e for e in store.events
            if e["event_type"] == "telegram_callback_malformed"
        ]
        self.assertEqual(len(malformed_events), 1)

    def test_unsupported_kill_returns_phase8_message(self) -> None:
        store = self._store()
        result = dp.dispatch_callback(
            store=store,
            kernel_url="postgresql://test/none",
            source_event_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            callback_query=self._callback(f"kill:{self.CANDIDATE_HEX}"),
        )
        self.assertIn("Phase 8", result["reply_text"])
        unsupported_events = [
            e for e in store.events
            if e["event_type"] == "telegram_callback_unsupported"
        ]
        self.assertEqual(len(unsupported_events), 1)


if __name__ == "__main__":
    unittest.main()
