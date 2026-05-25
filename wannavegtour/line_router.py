"""LINE event → worker dispatch with safety rules.

Sits between line_listener (raw HTTP / signature) and the actual workers
(availability_checker / historical_lookup). Pure logic — no I/O of its own
beyond what the injected workers/client perform. Easy to unit-test.

Policy (Pattern B — passive listening):
    Bot is a SILENT OBSERVER by default. Every text message is parsed and
    classified (intent recorded in audit log for training / replay), but
    no reply is sent unless the bot is explicitly @mentioned. This keeps
    the OP group's natural conversation undisturbed.

    @mention strips the bot reference from text, then routes:
        AVAILABILITY_CHECK → AvailabilityChecker  → reply
        HISTORICAL_LOOKUP  → HistoricalLookup     → reply
        PRICE_EDIT_HINT    → reply with refusal text (NEVER auto-execute;
                             also NEVER push to Telegram unsolicited)
        UNCLEAR            → reply with ack/help text

    No @mention:
        Any intent → silent. Audit log captures text + classified intent.

    Non-text / non-message events: silent.

Group whitelist: if line config's `target_groups` is non-empty, only
events from those groups are processed. Empty list = any group accepted.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .availability_checker import AvailabilityChecker
from .config import LineConfig
from .historical_lookup import HistoricalLookup
from .line_client import LineEvent
from .query_parser import QueryIntent, parse_query
from .response_formatter import format_historical, format_response


# Message returned when bot is @mentioned but the message isn't classifiable.
UNCLEAR_ACK_TEXT = (
    "🤔 看不出你想問什麼。試試：\n"
    "  • 『@bot 3/5 江南還剩多少？』(查名額)\n"
    "  • 『@bot 7/22 暑假成團多少人』(問歷史)\n"
    "  • 『@bot 今年賣最好的團』(排行)\n"
)

PRICE_EDIT_REFUSAL_TEXT = (
    "🙅 偵測到改價/改資訊指令（Type 2）— 自動執行尚未上線，請手動到 WordPress 後台處理。"
)


class DispatchAction(str, enum.Enum):
    """What the listener should do after router returns."""
    REPLY = "reply"                # send a LINE message back to the group / user
    SILENT = "silent"              # no LINE response, just log
    ALERT_TELEGRAM = "alert_telegram"  # reserved — currently unused in passive mode


@dataclass(frozen=True)
class DispatchResult:
    action: DispatchAction
    reply_text: str | None = None
    target_id: str | None = None         # groupId / userId to reply to
    reply_token: str | None = None       # for cheap reply (30s window)
    intent: str | None = None
    worker: str | None = None
    skip_reason: str | None = None       # why we went silent (for audit log)
    audit_extras: dict = field(default_factory=dict)


class LineRouter:
    """Dispatcher. Takes a parsed LineEvent + worker handles, returns a
    DispatchResult describing what the listener should do."""

    def __init__(
        self,
        line_config: LineConfig,
        availability: AvailabilityChecker,
        historical: HistoricalLookup,
    ) -> None:
        self.line_config = line_config
        self.availability = availability
        self.historical = historical

    def dispatch(self, event: LineEvent) -> DispatchResult:
        # 1. Non-message events: nothing to reply to.
        if event.event_type != "message" or event.message_type != "text" or not event.text:
            return DispatchResult(
                action=DispatchAction.SILENT, intent=None, worker=None,
                skip_reason=f"non-text event (type={event.event_type}, msg_type={event.message_type})",
            )

        # 2. Whitelist enforcement (if target_groups is set).
        # When a whitelist exists, the bot is intended for those groups ONLY.
        # Direct messages (source_type="user") and multi-person rooms must NOT
        # bypass the whitelist by virtue of having no groupId — they're rejected
        # outright. Empty whitelist = accept any source (current default).
        target_id = event.group_id or event.user_id
        if not self.line_config.accepts_any_group:
            if event.source_type != "group":
                return DispatchResult(
                    action=DispatchAction.SILENT, target_id=target_id,
                    skip_reason=f"non-group source {event.source_type!r} rejected (group whitelist active)",
                )
            if not self._group_allowed(event.group_id):
                return DispatchResult(
                    action=DispatchAction.SILENT, target_id=target_id,
                    skip_reason=f"group {event.group_id!r} not in target_groups whitelist",
                )

        # 3. PASSIVE LISTENING (Pattern B): without an @bot mention, the bot
        # stays silent. We still parse + classify the intent so the audit log
        # captures it as a training signal, but no LINE reply is sent.
        if not event.mention_is_self:
            parsed = parse_query(event.text)
            return DispatchResult(
                action=DispatchAction.SILENT,
                target_id=target_id,
                intent=parsed.intent.value, worker=None,
                skip_reason="passive listening: not @mentioned",
                audit_extras={
                    "would_have_replied": parsed.intent.value in (
                        QueryIntent.AVAILABILITY_CHECK.value,
                        QueryIntent.HISTORICAL_LOOKUP.value,
                    ),
                    "destination_hint": parsed.destination_hint,
                    "lifecycle_hint": (parsed.extras or {}).get("lifecycle_hint"),
                },
            )

        # 4. @mentioned — strip the bot reference and dispatch by intent.
        clean_text = _strip_bot_mention(
            event.text, event.mention_self_index, event.mention_self_length,
        )
        parsed = parse_query(clean_text)
        intent = parsed.intent

        if intent == QueryIntent.AVAILABILITY_CHECK:
            check = self.availability.check(parsed)
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=format_response(check),
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker="availability_checker",
                audit_extras={"result_kind": check.kind.value, "n_products": len(check.products),
                              "cleaned_text": clean_text},
            )

        if intent == QueryIntent.HISTORICAL_LOOKUP:
            hist = self.historical.lookup(parsed)
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=format_historical(hist),
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker="historical_lookup",
                audit_extras={"result_kind": hist.kind.value, "n_products": len(hist.products),
                              "cleaned_text": clean_text},
            )

        if intent == QueryIntent.PRICE_EDIT_HINT:
            # Bot was explicitly invoked AND asked to change price.
            # Reply with refusal so the user sees we heard but won't act.
            # No Telegram alert — even @mention does not authorize Telegram noise
            # under passive-listening discipline; user is in the loop already.
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=PRICE_EDIT_REFUSAL_TEXT,
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker=None,
                audit_extras={"original_text": event.text, "cleaned_text": clean_text},
            )

        # intent == UNCLEAR but @mentioned — give an ack so user knows we heard.
        return DispatchResult(
            action=DispatchAction.REPLY,
            reply_text=UNCLEAR_ACK_TEXT,
            target_id=target_id,
            reply_token=event.reply_token,
            intent=intent.value, worker=None,
            skip_reason="unclear but @mentioned, replying with ack",
            audit_extras={"cleaned_text": clean_text},
        )

    def _group_allowed(self, group_id: str | None) -> bool:
        if self.line_config.accepts_any_group:
            return True
        if not group_id:
            return False
        return group_id in self.line_config.target_groups


def _strip_bot_mention(text: str, index: int | None, length: int | None) -> str:
    """Remove the @bot substring at the LINE-provided index/length, then trim.

    LINE gives us exact char offsets for each mentionee — we use them directly
    instead of regex-guessing (display name varies: @Hermes小幫手, @283nbnhf,
    etc., and may contain CJK width oddities). If the indices are missing or
    out of bounds we fall back to the raw text so the parser still has data.
    """
    if not text:
        return ""
    if index is None or length is None or index < 0 or length <= 0:
        return text.strip()
    end = index + length
    if end > len(text):
        return text.strip()
    return (text[:index] + text[end:]).strip()
