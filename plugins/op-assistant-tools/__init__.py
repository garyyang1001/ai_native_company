"""op-assistant-tools plugin: 6-tool harness for wannavegtour OP LINE bot."""

from tools.registry import registry

from . import schemas
from . import tools


TOOLSET = "op_assistant"


def _always_available() -> bool:
    return True


_TOOL_DEFINITIONS = [
    ("query_intent", schemas.QUERY_INTENT, tools.query_intent),
    ("fetch_wc_data", schemas.FETCH_WC_DATA, tools.fetch_wc_data),
    ("compose_reply", schemas.COMPOSE_REPLY, tools.compose_reply),
    ("validate_reply", schemas.VALIDATE_REPLY, tools.validate_reply),
    ("send_reply", schemas.SEND_REPLY, tools.send_reply),
    ("escalate_to_gary", schemas.ESCALATE_TO_GARY, tools.escalate_to_gary),
]


registry.register(
    name="query_intent",
    toolset=TOOLSET,
    schema=schemas.QUERY_INTENT,
    handler=tools.query_intent,
    check_fn=_always_available,
)

registry.register(
    name="fetch_wc_data",
    toolset=TOOLSET,
    schema=schemas.FETCH_WC_DATA,
    handler=tools.fetch_wc_data,
    check_fn=_always_available,
)

registry.register(
    name="compose_reply",
    toolset=TOOLSET,
    schema=schemas.COMPOSE_REPLY,
    handler=tools.compose_reply,
    check_fn=_always_available,
)

registry.register(
    name="validate_reply",
    toolset=TOOLSET,
    schema=schemas.VALIDATE_REPLY,
    handler=tools.validate_reply,
    check_fn=_always_available,
)

registry.register(
    name="send_reply",
    toolset=TOOLSET,
    schema=schemas.SEND_REPLY,
    handler=tools.send_reply,
    check_fn=_always_available,
)

registry.register(
    name="escalate_to_gary",
    toolset=TOOLSET,
    schema=schemas.ESCALATE_TO_GARY,
    handler=tools.escalate_to_gary,
    check_fn=_always_available,
)


def register(ctx) -> None:
    """Register tools through the Hermes plugin context for plugin tracking."""
    for name, schema, handler in _TOOL_DEFINITIONS:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=_always_available,
        )
