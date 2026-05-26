"""OpenAI-style function schemas for the op-assistant 6-tool harness."""

INTENT_ENUM = [
    "availability",
    "historical",
    "aggregate",
    "help",
    "price_edit_refuse",
    "unknown",
]


QUERY_INTENT = {
    "name": "query_intent",
    "description": (
        "Forced first step for every OP assistant text message. Classify the "
        "incoming LINE text into one known intent and extract entities before "
        "any fetch, compose, send, or escalation work. Hermes /busy queue "
        "handles concurrent messages before this tool, and image or sticker "
        "events are filtered by the listener before they reach this tool. "
        "The handler returns a JSON string with intent, entities, confidence, "
        "and source. Source is one of deterministic, pattern_route, or llm. "
        "Do not answer the user directly from this result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The raw OP LINE text after the 小弟 wake prefix is removed.",
            }
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": INTENT_ENUM},
            "entities": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source": {
                "type": "string",
                "enum": ["deterministic", "pattern_route", "llm"],
            },
        },
        "required": ["intent", "entities", "confidence", "source"],
    },
}


FETCH_WC_DATA = {
    "name": "fetch_wc_data",
    "description": (
        "Fetch read-only WooCommerce data after query_intent has returned a "
        "supported intent and entities. Use for availability, historical, and "
        "aggregate lookups; help and price_edit_refuse may return empty data "
        "for template composition. This tool must not mutate WooCommerce, LINE, "
        "or any production system. The handler returns a JSON string containing "
        "the WC data needed by compose_reply and validate_reply."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": INTENT_ENUM,
                "description": "Intent returned by query_intent.",
            },
            "entities": {
                "type": "object",
                "description": "Entity object returned by query_intent; shape varies by intent.",
            },
        },
        "required": ["intent", "entities"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "description": "WooCommerce result subset relevant to the requested intent.",
    },
}


COMPOSE_REPLY = {
    "name": "compose_reply",
    "description": (
        "Compose the second LINE message body from verified intent and fetched "
        "data using deterministic templates. The draft body must not include "
        "the first-message prefix; send_reply automatically sends "
        "'稍等,我去查詢一下。' before the draft. For escalation flows, do not use "
        "this tool; call escalate_to_gary so the alternate prefix "
        "'稍等,我叫 Gary 出來面對。' can be used. This tool should not call an LLM."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": INTENT_ENUM,
                "description": "Intent being answered.",
            },
            "data": {
                "type": "object",
                "description": "Data returned by fetch_wc_data.",
            },
        },
        "required": ["intent", "data"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "properties": {
            "draft_reply_body": {
                "type": "string",
                "description": "Actual answer body without the LINE prefix message.",
            }
        },
        "required": ["draft_reply_body"],
    },
}


VALIDATE_REPLY = {
    "name": "validate_reply",
    "description": (
        "Validate a composed draft before any LINE send. Use after "
        "compose_reply and before send_reply for every non-escalation answer. "
        "Check that the draft is short enough for LINE, uses Traditional "
        "Chinese, does not leak secrets, does not mention forbidden mutation "
        "actions, and only states facts supported by the fetched data. If it "
        "fails, retry compose_reply with the retry_hint; after repeated failure, "
        "call escalate_to_gary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "draft": {
                "type": "string",
                "description": "Draft reply body returned by compose_reply.",
            },
            "intent": {
                "type": "string",
                "enum": INTENT_ENUM,
                "description": "Intent being answered.",
            },
            "data": {
                "type": "object",
                "description": "Data returned by fetch_wc_data.",
            },
        },
        "required": ["draft", "intent", "data"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "violations": {"type": "array", "items": {"type": "string"}},
            "retry_hint": {"type": "string"},
        },
        "required": ["passed", "violations", "retry_hint"],
    },
}


SEND_REPLY = {
    "name": "send_reply",
    "description": (
        "Send the approved OP assistant answer to the original LINE group. "
        "Only call after validate_reply passes. The agent passes only the "
        "draft answer body; the handler is responsible for sending two LINE "
        "messages: first '稍等,我去查詢一下。', then the draft body. Do not use this "
        "for escalation; escalate_to_gary owns the alternate first message "
        "'稍等,我叫 Gary 出來面對。'. Hermes handles /busy queue concurrency before "
        "tool execution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "group_id": {
                "type": "string",
                "description": "Original LINE group id for the OP conversation.",
            },
            "draft": {
                "type": "string",
                "description": "Validated answer body without the automatic prefix message.",
            },
        },
        "required": ["group_id", "draft"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "properties": {
            "sent": {"type": "boolean"},
            "message_ids": {"type": "array", "items": {"type": "string"}},
            "latency_ms": {"type": "integer", "minimum": 0},
        },
        "required": ["sent", "message_ids", "latency_ms"],
    },
}


ESCALATE_TO_GARY = {
    "name": "escalate_to_gary",
    "description": (
        "Escalate to Gary when intent is unknown, confidence is too low, a tool "
        "errors, validation repeatedly fails, or the SOUL instructions are "
        "unclear. Escalation should preserve the original context for review. "
        "For OP-facing escalation, the first LINE message is "
        "'稍等,我叫 Gary 出來面對。'. The handler records which escalation paths fired, "
        "such as jsonl, line_notify, or telegram_push. Do not call real external "
        "APIs during the Phase D stub."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Short reason for escalation.",
            },
            "context": {
                "type": "object",
                "description": "Structured context including original text, classifier output, drafts, violations, or tool errors.",
            },
            "group_id": {
                "type": "string",
                "description": "Original LINE group id for the OP conversation.",
            },
        },
        "required": ["reason", "context", "group_id"],
        "additionalProperties": False,
    },
    "returns": {
        "type": "object",
        "properties": {
            "escalated": {"type": "boolean"},
            "channels": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["jsonl", "line_notify", "telegram_push"],
                },
            },
        },
        "required": ["escalated", "channels"],
    },
}


ALL_SCHEMAS = [
    QUERY_INTENT,
    FETCH_WC_DATA,
    COMPOSE_REPLY,
    VALIDATE_REPLY,
    SEND_REPLY,
    ESCALATE_TO_GARY,
]
