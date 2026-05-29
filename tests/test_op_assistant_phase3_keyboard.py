"""V0.3 Phase 3 — Telegram inline keyboard rendering tests.

Verifies the keyboard shape Phase 3 sender produces matches the
``callback_data`` v0 contract (32-hex UUID, ``<action>:<candidate_id>``
format, three buttons per candidate).
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

REPO = "/home/wannavegtour/Desktop/AI Native Company/Gary"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("KERNEL_DATABASE_URL", "postgresql://test:test@localhost/none")


def _load_daily_curate():
    path = Path(REPO) / "scripts" / "op_assistant" / "op_assistant_daily_curate.py"
    spec = importlib.util.spec_from_file_location("op_daily_curate_p3", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dc = _load_daily_curate()

CALLBACK_RE = re.compile(r"^(apv|rej|vw|kill|killall):([0-9a-f]{32})$")


class RenderKeyboardTests(unittest.TestCase):
    def test_empty_returns_none(self) -> None:
        self.assertIsNone(dc._render_inline_keyboard([]))

    def test_single_candidate_produces_one_row_three_buttons(self) -> None:
        keyboard = dc._render_inline_keyboard([
            {
                "id": "3f356f63-1a3e-539b-9478-a59dcb476611",
                "label_index": 1,
                "proposal_type": "availability_keyword",
                "value": "沒有賣完",
            },
        ])
        assert keyboard is not None
        self.assertEqual(list(keyboard.keys()), ["inline_keyboard"])
        rows = keyboard["inline_keyboard"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 3)

    def test_callback_data_matches_contract_regex(self) -> None:
        keyboard = dc._render_inline_keyboard([
            {
                "id": "3f356f63-1a3e-539b-9478-a59dcb476611",
                "label_index": 1,
                "proposal_type": "availability_keyword",
                "value": "x",
            },
            {
                "id": "1299448b-e68e-5df8-a019-7f848f32d6d2",
                "label_index": 2,
                "proposal_type": "availability_regex",
                "value": "y",
            },
        ])
        assert keyboard is not None
        for row in keyboard["inline_keyboard"]:
            for button in row:
                m = CALLBACK_RE.fullmatch(button["callback_data"])
                self.assertIsNotNone(
                    m,
                    f"callback_data {button['callback_data']!r} fails v0 regex",
                )

    def test_button_actions_are_apv_rej_vw_only_for_phase3(self) -> None:
        """Phase 3 stage does not render KILL buttons — those wait for
        Phase 8 to create status='applied' candidates.
        """
        keyboard = dc._render_inline_keyboard([
            {"id": "3f356f63-1a3e-539b-9478-a59dcb476611", "label_index": 1,
             "proposal_type": "availability_keyword", "value": "x"},
        ])
        assert keyboard is not None
        actions = [
            button["callback_data"].split(":")[0]
            for button in keyboard["inline_keyboard"][0]
        ]
        self.assertEqual(actions, ["apv", "rej", "vw"])

    def test_button_text_uses_label_index(self) -> None:
        keyboard = dc._render_inline_keyboard([
            {"id": "11111111-1111-1111-1111-111111111111", "label_index": 1,
             "proposal_type": "availability_keyword", "value": "a"},
            {"id": "22222222-2222-2222-2222-222222222222", "label_index": 2,
             "proposal_type": "availability_regex", "value": "b"},
        ])
        assert keyboard is not None
        first_texts = [b["text"] for b in keyboard["inline_keyboard"][0]]
        second_texts = [b["text"] for b in keyboard["inline_keyboard"][1]]
        for t in first_texts:
            self.assertIn(" 1", t)
        for t in second_texts:
            self.assertIn(" 2", t)

    def test_dashes_stripped_lowercase(self) -> None:
        """callback_data uses 32-hex form: no dashes, all lowercase."""
        keyboard = dc._render_inline_keyboard([
            {"id": "3F356F63-1A3E-539B-9478-A59DCB476611", "label_index": 1,
             "proposal_type": "availability_keyword", "value": "x"},
        ])
        assert keyboard is not None
        cd = keyboard["inline_keyboard"][0][0]["callback_data"]
        self.assertNotIn("-", cd)
        # Whole string lowercase except the action prefix which is already lc.
        self.assertEqual(cd, cd.lower())


class PersistCandidatesReturnsListTests(unittest.TestCase):
    """Phase 3 needs ``_persist_candidates`` to expose the list of accepted
    candidates so the sender can render rows in the right order. Round 8
    extends the return dict with ``candidates``; this test guards that
    contract.
    """

    class FakeStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list]] = []

        def execute(self, sql: str, params=None) -> None:
            self.calls.append((sql, list(params or [])))

    def test_returns_candidates_field_with_id_label_index(self) -> None:
        store = self.FakeStore()
        actionables = [
            {"type": "keyword", "value": "沒有賣完", "reason": "x"},
            {"type": "regex", "value": "有哪些團.*?沒有賣完", "reason": "y"},
            {"type": "intent", "value": "skip me", "reason": "z"},
        ]
        out = dc._persist_candidates(
            store, "65881cd8-c556-5690-9260-2959302d9e5f", actionables,
            dry_run=False,
        )
        self.assertEqual(out["created_attempted"], 2)
        self.assertEqual(out["rejected"], 1)
        self.assertIn("candidates", out)
        cands = out["candidates"]
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["label_index"], 1)
        self.assertEqual(cands[1]["label_index"], 2)
        self.assertEqual(cands[0]["proposal_type"], "availability_keyword")
        self.assertEqual(cands[1]["proposal_type"], "availability_regex")


if __name__ == "__main__":
    unittest.main()
