"""V0.3 Phase 7 — patch emitter + AST guard tests.

Each test on a fresh temp file or in-memory source string. The git
commit path is exercised only by the candidate-driven entry point in
``emit_for_candidate``; here we cover the pure functions and the
guard logic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
import unittest
from pathlib import Path

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("KERNEL_DATABASE_URL", "postgresql://test:test@localhost/none")


def _load_emitter():
    path = Path(REPO) / "scripts" / "op_assistant" / "op_assistant_patch_emitter.py"
    spec = importlib.util.spec_from_file_location("op_patch_emitter_mod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pe = _load_emitter()


MINIMAL_SOURCE = textwrap.dedent('''
    """Tiny test parser."""

    LIFECYCLE_MARKERS = ("成團",)

    _AVAILABILITY_KEYWORDS = (
        "還有",
        "還剩",
    )

    def parse_query(text):
        return text
''').lstrip()


# ---------------------------------------------------------------------
# emit_keyword_patch
# ---------------------------------------------------------------------

class EmitKeywordPatchTests(unittest.TestCase):
    def test_adds_keyword_preserving_existing(self) -> None:
        new = pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        self.assertIn('"沒有賣完"', new)
        self.assertIn('"還有"', new)
        self.assertIn('"還剩"', new)

    def test_idempotent_keyword_raises_already_present(self) -> None:
        with self.assertRaises(pe.KeywordAlreadyPresentError):
            pe.emit_keyword_patch(MINIMAL_SOURCE, "還有")

    def test_missing_target_raises_too_invasive(self) -> None:
        src = "X = 1\n"
        with self.assertRaises(pe.PatchTooInvasiveError):
            pe.emit_keyword_patch(src, "新詞")

    def test_non_tuple_target_raises_too_invasive(self) -> None:
        src = textwrap.dedent('''
            _AVAILABILITY_KEYWORDS = ["a", "b"]
        ''').lstrip()
        # List is not Tuple — the guard rejects it explicitly so we don't
        # have to assume list-vs-tuple semantics elsewhere.
        with self.assertRaises(pe.PatchTooInvasiveError):
            pe.emit_keyword_patch(src, "c")


# ---------------------------------------------------------------------
# AST guard
# ---------------------------------------------------------------------

class AstGuardTests(unittest.TestCase):
    def test_happy_patch_passes(self) -> None:
        new = pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        # Must not raise
        pe.assert_patch_is_surgical(MINIMAL_SOURCE, new, "沒有賣完")

    def test_added_keyword_must_match_expected(self) -> None:
        new = pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        with self.assertRaises(pe.PatchTooInvasiveError) as ctx:
            pe.assert_patch_is_surgical(MINIMAL_SOURCE, new, "別的詞")
        self.assertIn("added element", str(ctx.exception))

    def test_extra_top_level_statement_rejected(self) -> None:
        new = pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        # Sneak in an extra top-level assignment
        new += "\nINJECTED = 1\n"
        with self.assertRaises(pe.PatchTooInvasiveError) as ctx:
            pe.assert_patch_is_surgical(MINIMAL_SOURCE, new, "沒有賣完")
        self.assertIn("statement count changed", str(ctx.exception))

    def test_new_import_rejected(self) -> None:
        new = "import os\n" + pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        with self.assertRaises(pe.PatchTooInvasiveError):
            pe.assert_patch_is_surgical(MINIMAL_SOURCE, new, "沒有賣完")

    def test_existing_keyword_changed_rejected(self) -> None:
        bad = MINIMAL_SOURCE.replace('"還有"', '"還沒"')
        # bad has the same tuple length, so the "+1" length check would
        # not catch it; the per-element comparison must.
        with self.assertRaises(pe.PatchTooInvasiveError):
            pe.assert_patch_is_surgical(MINIMAL_SOURCE, bad, "沒有賣完")

    def test_function_body_change_rejected(self) -> None:
        # Add a keyword AND change the function body — guard must reject
        # because parse_query's AST dump differs.
        new = pe.emit_keyword_patch(MINIMAL_SOURCE, "沒有賣完")
        new = new.replace("return text", "return text.upper()")
        with self.assertRaises(pe.PatchTooInvasiveError) as ctx:
            pe.assert_patch_is_surgical(MINIMAL_SOURCE, new, "沒有賣完")
        self.assertIn("statement #", str(ctx.exception))


# ---------------------------------------------------------------------
# emit_for_candidate entry-point — uses FakeStore
# ---------------------------------------------------------------------

class FakeTxn:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store

    def execute(self, sql: str, params=None) -> None:
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "UPDATE improvement_candidates SET status" in sql_norm:
            # the emit_for_candidate code uses literal status values in the
            # SQL ("SET status = 'patch_emitted'") and a single ? param for
            # the candidate id, so extract both from the SQL string here.
            cid = params_list[0]
            if cid in self._store.candidates:
                new_status = sql_norm.split("SET status = '")[1].split("'")[0]
                expected = sql_norm.split("AND status = '")[1].split("'")[0]
                if self._store.candidates[cid]["status"] == expected:
                    self._store.candidates[cid]["status"] = new_status
        elif "INSERT INTO events" in sql_norm:
            self._store.events.append({
                "id": params_list[0],
                "event_type": params_list[1],
                "payload": params_list[2],
                "created_at": params_list[3],
            })


class FakeStore:
    def __init__(self) -> None:
        self.candidates: dict[str, dict[str, str]] = {}
        self.approvals: list[dict] = []
        self.events: list[dict] = []

    def fetch_one(self, sql: str, params=None):
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "FROM improvement_candidates WHERE id" in sql_norm:
            return self.candidates.get(params_list[0])
        if "FROM approvals WHERE candidate_id" in sql_norm:
            cid = params_list[0]
            for a in reversed(self.approvals):
                if a.get("candidate_id") == cid and a.get("decision") == "approved":
                    return {"approved_by": a.get("approved_by")}
            return None

    def execute(self, sql: str, params=None) -> None:
        # mirror the transaction-less path used by some events writes
        sql_norm = " ".join(sql.split())
        params_list = list(params or [])
        if "INSERT INTO events" in sql_norm:
            self.events.append({
                "id": params_list[0],
                "event_type": params_list[1],
                "payload": params_list[2],
                "created_at": params_list[3],
            })

    from contextlib import contextmanager

    @contextmanager
    def transaction(self):
        tx = FakeTxn(self)
        yield tx


class EmitForCandidateTests(unittest.TestCase):
    def test_missing_candidate_returns_missing(self) -> None:
        store = FakeStore()
        out = pe.emit_for_candidate(store, "nope")
        self.assertEqual(out["status"], "missing")

    def test_wrong_state_when_not_sandbox_verified(self) -> None:
        store = FakeStore()
        store.candidates["abc"] = {
            "id": "abc", "status": "draft",
            "proposal_type": "availability_keyword",
            "typed_payload": {"value": "x"},
        }
        out = pe.emit_for_candidate(store, "abc")
        self.assertEqual(out["status"], "wrong_state")
        self.assertEqual(out["candidate_status"], "draft")

    def test_regex_proposal_marked_too_invasive(self) -> None:
        store = FakeStore()
        store.candidates["abc"] = {
            "id": "abc", "status": "sandbox_verified",
            "proposal_type": "availability_regex",
            "typed_payload": {"value": "(\\d+)月"},
        }
        out = pe.emit_for_candidate(store, "abc")
        self.assertEqual(out["status"], "patch_too_invasive")
        self.assertEqual(store.candidates["abc"]["status"], "patch_too_invasive")
        events = [e for e in store.events if e["event_type"] == "candidate_status_changed"]
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
