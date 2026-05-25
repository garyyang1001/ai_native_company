"""LINE event → worker dispatch with safety rules.

Sits between line_listener (raw HTTP / signature) and the actual workers
(availability_checker / historical_lookup). Pure logic — no I/O of its own
beyond what the injected workers/client perform. Easy to unit-test.

Policy (Pattern C in design docs):
    intent == AVAILABILITY_CHECK   → AvailabilityChecker     → reply
    intent == HISTORICAL_LOOKUP    → HistoricalLookup        → reply
    intent == PRICE_EDIT_HINT      → NO REPLY; log + alert   → telegram
                                     (we never auto-execute pricing changes)
    intent == UNCLEAR              → silent (no reply)
                                     UNLESS mention.isSelf=true → ack message
    event.type != "message"        → silent (joins/leaves only logged)

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
    "  • 『3/5 江南還剩多少？』(查名額)\n"
    "  • 『7/22 暑假成團多少人』(問歷史)\n"
    "  • 『今年賣最好的團』(排行)\n"
)

PRICE_EDIT_REFUSAL_TEXT = (
    "🙅 偵測到改價/改資訊指令（Type 2）— 自動執行尚未上線，請手動處理。"
    "Gary 已被 Telegram 通知。"
)


class DispatchAction(str, enum.Enum):
    """What the listener should do after router returns."""
    REPLY = "reply"                # send a LINE message back to the group / user
    SILENT = "silent"              # no LINE response, just log
    ALERT_TELEGRAM = "alert_telegram"  # log + push to Telegram (Type 2 hint)


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

        # 3. Parse.
        parsed = parse_query(event.text)
        intent = parsed.intent

        # 4. Route by intent.
        if intent == QueryIntent.AVAILABILITY_CHECK:
            check = self.availability.check(parsed)
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=format_response(check),
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker="availability_checker",
                audit_extras={"result_kind": check.kind.value, "n_products": len(check.products)},
            )

        if intent == QueryIntent.HISTORICAL_LOOKUP:
            hist = self.historical.lookup(parsed)
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=format_historical(hist),
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker="historical_lookup",
                audit_extras={"result_kind": hist.kind.value, "n_products": len(hist.products)},
            )

        if intent == QueryIntent.PRICE_EDIT_HINT:
            # Never auto-execute pricing changes. Alert Gary, do not reply in LINE.
            return DispatchResult(
                action=DispatchAction.ALERT_TELEGRAM,
                reply_text=PRICE_EDIT_REFUSAL_TEXT,
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker=None,
                audit_extras={"original_text": event.text},
            )

        # intent == UNCLEAR
        # If bot was @mentioned explicitly, acknowledge so user knows we heard them.
        # Otherwise stay silent — don't reply to every chat message.
        if event.mention_is_self:
            return DispatchResult(
                action=DispatchAction.REPLY,
                reply_text=UNCLEAR_ACK_TEXT,
                target_id=target_id,
                reply_token=event.reply_token,
                intent=intent.value, worker=None,
                skip_reason="unclear but @mentioned, replying with ack",
            )

        return DispatchResult(
            action=DispatchAction.SILENT, target_id=target_id,
            intent=intent.value, worker=None,
            skip_reason="intent=UNCLEAR and not @mentioned",
        )

    def _group_allowed(self, group_id: str | None) -> bool:
        if self.line_config.accepts_any_group:
            return True
        if not group_id:
            return False
        return group_id in self.line_config.target_groups
