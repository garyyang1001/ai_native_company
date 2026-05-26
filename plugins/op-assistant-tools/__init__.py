"""op-assistant-tools plugin: 6-tool harness for wannavegtour OP LINE bot."""

try:
    from tools.registry import registry
except ModuleNotFoundError:
    registry = None

try:
    from . import schemas
    from . import tools
except ImportError:
    import importlib.util
    from pathlib import Path

    def _load_local_module(module_name: str, filename: str):
        path = Path(__file__).with_name(filename)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {filename}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    schemas = _load_local_module("op_assistant_tools_schemas", "schemas.py")
    tools = _load_local_module("op_assistant_tools_handlers", "tools.py")


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


if registry is not None:
    for name, schema, handler in _TOOL_DEFINITIONS:
        registry.register(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
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
