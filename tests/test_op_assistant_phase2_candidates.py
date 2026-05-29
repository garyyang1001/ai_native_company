"""V0.3 Phase 2 simple 版 — _persist_candidates 行為測試.

Cover Round 4 codex review 兩個必要 guards:
* Proposal type whitelist(keyword/regex,其他 reject)
* Idempotency via deterministic uuid5(同 actionable 跑兩次不雙寫)

不打真 PostgreSQL — FakeStore capture execute calls,因為 Phase 2 邏輯
不依賴 fetch 返回值。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)


# Skip module-level os.environ["KERNEL_DATABASE_URL"] eager-read by setting it
# before import. Real path read uses ~/.hermes profile env on prod runs.
os.environ.setdefault("KERNEL_DATABASE_URL", "postgresql://test:test@localhost/none")


def _load_daily_curate():
    """daily_curate has a dash-named parent dir, so importlib does the work."""
    path = Path(REPO) / "scripts" / "op_assistant" / "op_assistant_daily_curate.py"
    spec = importlib.util.spec_from_file_location("op_daily_curate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dc = _load_daily_curate()


class FakeStore:
    """Captures every execute call as (sql_normalized, params)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []
        self._seen_candidate_ids: set[str] = set()

    def execute(self, sql: str, params=None) -> None:
        # Strip whitespace so test assertions can match more loosely.
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        # Simulate ON CONFLICT DO NOTHING for the candidate INSERT path.
        if "INSERT INTO improvement_candidates" in sql_norm and \
                "ON CONFLICT (id) DO NOTHING" in sql_norm:
            cid = params_list[0]
            if cid in self._seen_candidate_ids:
                # PG would skip the INSERT;we record the call but flag it.
                self.calls.append((sql_norm, params_list + ["__CONFLICT_SKIPPED__"]))
                return
            self._seen_candidate_ids.add(cid)
        self.calls.append((sql_norm, params_list))

    def by_sql_substring(self, substr: str) -> list[list[Any]]:
        return [p for s, p in self.calls if substr in s]


SUMMARY_EVENT_ID = "65881cd8-c556-5690-9260-2959302d9e5f"


def _kw_actionable(value="沒有賣完", reason="重複出現"):
    return {"type": "keyword", "value": value, "reason": reason}


def _regex_actionable(value=r"有哪些團.*?沒有賣完", reason="完整句型"):
    return {"type": "regex", "value": value, "reason": reason}


def _intent_actionable():
    return {"type": "intent", "value": "check_remaining_availability", "reason": "新意圖"}


class WhitelistTests(unittest.TestCase):
    def test_keyword_writes_candidate(self) -> None:
        store = FakeStore()
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, [_kw_actionable()], dry_run=False,
        )
        self.assertEqual(counts, {"created_attempted": 1, "rejected": 0})

        inserts = store.by_sql_substring("INSERT INTO improvement_candidates")
        self.assertEqual(len(inserts), 1)
        # params order: id, status, proposal_type, typed_payload, source_event_id, created_at
        params = inserts[0]
        self.assertEqual(params[1], "draft")
        self.assertEqual(params[2], "availability_keyword")
        # typed_payload is JsonParam(value=json_string) — decode it
        decoded = json.loads(params[3].value)
        self.assertEqual(decoded["value"], "沒有賣完")
        self.assertEqual(decoded["type"], "keyword")
        self.assertEqual(params[4], SUMMARY_EVENT_ID)

    def test_regex_writes_candidate(self) -> None:
        store = FakeStore()
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, [_regex_actionable()], dry_run=False,
        )
        self.assertEqual(counts, {"created_attempted": 1, "rejected": 0})
        inserts = store.by_sql_substring("INSERT INTO improvement_candidates")
        self.assertEqual(inserts[0][2], "availability_regex")

    def test_intent_is_rejected_to_events(self) -> None:
        store = FakeStore()
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, [_intent_actionable()], dry_run=False,
        )
        self.assertEqual(counts, {"created_attempted": 0, "rejected": 1})

        # No candidate INSERT
        self.assertEqual(store.by_sql_substring("INSERT INTO improvement_candidates"), [])
        # One reject event
        rejects = store.by_sql_substring(
            "INSERT INTO events (id, event_type, payload, created_at)"
        )
        self.assertEqual(len(rejects), 1)
        # event_type position is index 1
        self.assertEqual(rejects[0][1], "improvement_candidate_rejected")

    def test_unknown_type_label_rejected(self) -> None:
        """Codex xhigh #1 — gemma4 可能吐 'keywords' / 'availability_keyword'
        / 空值。全部走 reject path,不 silent drop。
        """
        store = FakeStore()
        cases = [
            {"type": "keywords"},
            {"type": "availability_keyword"},
            {"type": ""},
            {"value": "no type at all"},
        ]
        counts = dc._persist_candidates(store, SUMMARY_EVENT_ID, cases, dry_run=False)
        self.assertEqual(counts, {"created_attempted": 0, "rejected": 4})
        rejects = store.by_sql_substring(
            "INSERT INTO events (id, event_type, payload, created_at)"
        )
        self.assertEqual(len(rejects), 4)


class IdempotencyTests(unittest.TestCase):
    def test_same_summary_twice_does_not_double_write(self) -> None:
        """Codex xhigh #2 — daily_curate 重跑 / cron retry 必須冪等."""
        actionables = [_kw_actionable(), _regex_actionable()]
        store = FakeStore()

        first = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, actionables, dry_run=False,
        )
        second = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, actionables, dry_run=False,
        )

        # Both attempts increment counter (we don't track PG conflicts at the
        # Python layer);but FakeStore simulates the ON CONFLICT DO NOTHING
        # and marks the second pair as skipped.
        self.assertEqual(first["created_attempted"], 2)
        self.assertEqual(second["created_attempted"], 2)

        inserts = store.by_sql_substring("INSERT INTO improvement_candidates")
        successful = [p for p in inserts if p[-1] != "__CONFLICT_SKIPPED__"]
        skipped = [p for p in inserts if p[-1] == "__CONFLICT_SKIPPED__"]
        self.assertEqual(len(successful), 2, "first run lands 2 rows")
        self.assertEqual(len(skipped), 2, "second run hits ON CONFLICT for both")

    def test_deterministic_candidate_id(self) -> None:
        actionables = [_kw_actionable()]
        s1 = FakeStore()
        s2 = FakeStore()
        dc._persist_candidates(s1, SUMMARY_EVENT_ID, actionables, dry_run=False)
        dc._persist_candidates(s2, SUMMARY_EVENT_ID, actionables, dry_run=False)
        id1 = s1.by_sql_substring("INSERT INTO improvement_candidates")[0][0]
        id2 = s2.by_sql_substring("INSERT INTO improvement_candidates")[0][0]
        self.assertEqual(id1, id2,
                          "candidate id must be deterministic from (summary, index)")

    def test_different_index_gets_different_id(self) -> None:
        actionables = [_kw_actionable(value="a"), _kw_actionable(value="b")]
        store = FakeStore()
        dc._persist_candidates(store, SUMMARY_EVENT_ID, actionables, dry_run=False)
        ids = [p[0] for p in store.by_sql_substring("INSERT INTO improvement_candidates")]
        self.assertEqual(len(set(ids)), 2)

    def test_reject_event_id_is_deterministic(self) -> None:
        """Re-run must not double-write rejected events either(prod
        verification caught this in Round 5 — uuid4 in reject path was
        regenerating each run)."""
        s1 = FakeStore()
        s2 = FakeStore()
        dc._persist_candidates(s1, SUMMARY_EVENT_ID, [_intent_actionable()], dry_run=False)
        dc._persist_candidates(s2, SUMMARY_EVENT_ID, [_intent_actionable()], dry_run=False)
        id1 = s1.by_sql_substring("INSERT INTO events")[0][0]
        id2 = s2.by_sql_substring("INSERT INTO events")[0][0]
        self.assertEqual(id1, id2,
                          "reject event id must be deterministic from (summary, index)")


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self) -> None:
        store = FakeStore()
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID,
            [_kw_actionable(), _regex_actionable(), _intent_actionable()],
            dry_run=True,
        )
        # counters still tick so the run() print line is informative
        self.assertEqual(counts, {"created_attempted": 2, "rejected": 1})
        # but no execute() calls landed
        self.assertEqual(store.calls, [])


class MixedActionableTests(unittest.TestCase):
    def test_mixed_keyword_regex_intent_all_counted(self) -> None:
        store = FakeStore()
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID,
            [_kw_actionable(), _regex_actionable(), _intent_actionable(),
             {"type": "weird"}],
            dry_run=False,
        )
        self.assertEqual(counts, {"created_attempted": 2, "rejected": 2})

    def test_uppercase_type_is_normalised(self) -> None:
        store = FakeStore()
        actionable = {"type": "KEYWORD", "value": "x"}
        counts = dc._persist_candidates(
            store, SUMMARY_EVENT_ID, [actionable], dry_run=False,
        )
        self.assertEqual(counts["created_attempted"], 1)
        inserts = store.by_sql_substring("INSERT INTO improvement_candidates")
        self.assertEqual(inserts[0][2], "availability_keyword")


if __name__ == "__main__":
    unittest.main()
