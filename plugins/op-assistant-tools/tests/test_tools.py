"""pytest tests for op-assistant-tools handlers."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/home/wannavegtour/Desktop/AI Native Company/Gary")
sys.path.insert(0, "/home/wannavegtour/.hermes/plugins/op-assistant-tools")

import tools


def load(payload):
    return json.loads(payload)


class TestQueryIntent:
    def test_empty(self):
        result = load(tools.query_intent({"text": ""}))

        assert result["intent"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["source"] == "empty_input"

    def test_deterministic_hit(self):
        result = load(tools.query_intent({"text": "9/15 日本還有嗎"}))

        assert result["intent"] == "availability"
        assert result["confidence"] == 1.0
        assert result["source"] == "deterministic"
        assert result["entities"]["tour_keyword"] == "日本"
        assert result["entities"]["date_hint"] == "9/15"

    def test_ambiguous_unknown(self, monkeypatch):
        monkeypatch.setattr(tools, "_call_llm_for_intent", lambda text: (None, {}, 0.0))

        result = load(tools.query_intent({"text": "嗯"}))

        assert result["intent"] == "unknown"
        assert result["source"] == "llm_low_confidence"


class TestFetchWcData:
    def test_help_static(self):
        result = load(tools.fetch_wc_data({"intent": "help"}))

        assert result["intent"] == "help"
        assert result["source"] == "static"
        assert "help_text" in result["data"]

    def test_price_edit_refuse(self):
        result = load(tools.fetch_wc_data({"intent": "price_edit_refuse"}))

        assert result["intent"] == "price_edit_refuse"
        assert result["source"] == "policy"
        assert result["data"]["refusal"] is True

    def test_unknown(self):
        result = load(tools.fetch_wc_data({"intent": "unknown"}))

        assert result["intent"] == "unknown"
        assert result["source"] == "no_fetcher"
        assert result["data"] is None

    @pytest.mark.skip(reason="requires real WooCommerce API")
    def test_availability_live(self):
        tools.fetch_wc_data({"intent": "availability", "entities": {}, "dry_run": False})


class TestComposeReply:
    def test_help_template_hits(self):
        result = load(
            tools.compose_reply(
                {
                    "intent": "help",
                    "data": {
                        "help_text": "可以查團、查歷史成團/額滿、查熱門排行；改價或修改資料請 Gary/OP 手動處理。"
                    },
                }
            )
        )

        assert result["source"] == "template"
        assert "可以查團" in result["draft_reply_body"]

    def test_price_edit_template_hits(self):
        result = load(
            tools.compose_reply(
                {"intent": "price_edit_refuse", "data": {"refusal": True}}
            )
        )

        assert result["source"] == "template"
        assert "只查詢不改資料" in result["draft_reply_body"]

    @pytest.mark.skip(reason="requires real LLM API")
    def test_compose_llm_fallback(self):
        tools.compose_reply({"intent": "unknown", "data": {"custom": True}})


class TestValidateReply:
    def test_pass_clean_text(self):
        result = load(
            tools.validate_reply(
                {
                    "draft": "素食日本 9 日 9/15 出發,差 4 位成團。",
                    "intent": "availability",
                    "data": {"tour_name": "素食日本 9 日"},
                }
            )
        )

        assert result["passed"] is True
        assert result["violations"] == []

    def test_length_violation(self):
        result = load(tools.validate_reply({"draft": "X" * 250}))

        assert result["passed"] is False
        assert any("length_over_200" in violation for violation in result["violations"])

    def test_forbidden_word(self):
        result = load(tools.validate_reply({"draft": "保證一定成團,免費招待您"}))

        assert result["passed"] is False
        assert any("forbidden_word" in violation for violation in result["violations"])

    def test_emoji_violation(self):
        result = load(tools.validate_reply({"draft": "好的 😊 我去查"}))

        assert result["passed"] is False
        assert "emoji_found" in result["violations"]

    def test_simplified_chars(self):
        result = load(tools.validate_reply({"draft": "这个团还有吗"}))

        assert result["passed"] is False
        assert any("simplified_chars" in violation for violation in result["violations"])

    def test_prefix_duplication(self):
        result = load(tools.validate_reply({"draft": "稍等,我去查詢一下。團還在"}))

        assert result["passed"] is False
        assert any("draft_includes_prefix" in violation for violation in result["violations"])

    def test_hallucinated_tour(self):
        result = load(
            tools.validate_reply(
                {
                    "draft": "素食韓國 5 日團還有位。",
                    "data": {"tour_name": "素食日本 9 日"},
                }
            )
        )

        assert result["passed"] is False
        assert any("hallucinated_tour" in violation for violation in result["violations"])


class FakeLineClient:
    def __init__(self):
        self.calls = []

    def push_text(self, to, text):
        self.calls.append((to, text))


class TestSendReply:
    def test_normal_two_messages(self):
        result = load(
            tools.send_reply(
                {"group_id": "TEST_GROUP_DRYRUN", "draft": "團 9/15 出發,差 4 位成團"}
            )
        )

        assert result["sent"] is True
        assert len(result["message_ids"]) == 2
        assert result["dry_run"] is True
        assert result["prefix"] == "稍等,我去查詢一下。"

    def test_escalate_one_message(self):
        result = load(
            tools.send_reply(
                {"group_id": "TEST_GROUP_DRYRUN", "draft": "", "is_escalate": True}
            )
        )

        assert result["sent"] is True
        assert len(result["message_ids"]) == 1
        assert "Gary" in result["prefix"]

    def test_missing_args(self):
        result = load(tools.send_reply({"group_id": "", "draft": "內容"}))

        assert result["sent"] is False
        assert result["reason"] == "missing group_id or draft"

    def test_non_text_ignored(self):
        result = load(
            tools.send_reply(
                {
                    "group_id": "TEST_GROUP_DRYRUN",
                    "draft": "內容",
                    "message_type": "image",
                }
            )
        )

        assert result["sent"] is False
        assert result["reason"] == "non-text-ignored"

    def test_non_dry_run_uses_line_client(self, monkeypatch):
        fake_client = FakeLineClient()
        monkeypatch.setattr(tools, "_make_line_client", lambda: fake_client)

        result = load(
            tools.send_reply(
                {"group_id": "FAKE_GROUP", "draft": "回覆內容", "dry_run": False}
            )
        )

        assert result["sent"] is True
        assert result["dry_run"] is False
        assert fake_client.calls == [
            ("FAKE_GROUP", "稍等,我去查詢一下。"),
            ("FAKE_GROUP", "回覆內容"),
        ]

    @pytest.mark.skip(reason="requires real LINE API")
    def test_line_push_live(self):
        tools.send_reply({"group_id": "REAL_GROUP", "draft": "live", "dry_run": False})


class TestEscalateToGary:
    def test_writes_jsonl(self, tmp_path, monkeypatch):
        jsonl_path = tmp_path / "wannavegtour.jsonl"
        monkeypatch.setattr(tools, "ESCALATIONS_JSONL", str(jsonl_path))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "fake-chat")

        result = load(
            tools.escalate_to_gary(
                {
                    "reason": "intent unclear",
                    "context": {"original_text": "嗯", "intent": "unknown"},
                    "group_id": "TEST_GROUP_DRYRUN",
                    "dry_run": True,
                }
            )
        )

        assert result["escalated"] is True
        assert "jsonl" in result["channels"]
        rows = jsonl_path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1
        record = json.loads(rows[0])
        assert record["reason"] == "intent unclear"
        assert record["context"]["original_text"] == "嗯"

    def test_dryrun_channels(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "ESCALATIONS_JSONL", str(tmp_path / "esc.jsonl"))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "fake-chat")

        result = load(
            tools.escalate_to_gary(
                {
                    "reason": "needs human",
                    "context": {"original_text": "?", "intent": "unknown"},
                    "group_id": "TEST_GROUP_DRYRUN",
                    "dry_run": True,
                }
            )
        )

        assert result["dry_run"] is True
        assert result["channels"] == ["jsonl", "line_notice", "telegram_dryrun"]
        assert result["errors"] == {}

    def test_non_text_ignored(self):
        result = load(tools.escalate_to_gary({"message_type": "sticker"}))

        assert result["sent"] is False
        assert result["reason"] == "non-text-ignored"

    @pytest.mark.skip(reason="requires real Telegram API")
    def test_telegram_live(self):
        tools.escalate_to_gary(
            {
                "reason": "live",
                "context": {},
                "group_id": "REAL_GROUP",
                "dry_run": False,
            }
        )
