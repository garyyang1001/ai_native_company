"""Phase D stub handlers for op-assistant-tools."""

import json


def _stub(tool_name: str, args: dict) -> str:
    return json.dumps(
        {
            "status": "stub",
            "tool": tool_name,
            "args": args,
            "note": "Phase E/F will fill real logic.",
        },
        ensure_ascii=False,
    )


def query_intent(args: dict, **kwargs) -> str:
    return _stub("query_intent", args)


def fetch_wc_data(args: dict, **kwargs) -> str:
    return _stub("fetch_wc_data", args)


def compose_reply(args: dict, **kwargs) -> str:
    return _stub("compose_reply", args)


def validate_reply(args: dict, **kwargs) -> str:
    return _stub("validate_reply", args)


def send_reply(args: dict, **kwargs) -> str:
    return _stub("send_reply", args)


def escalate_to_gary(args: dict, **kwargs) -> str:
    return _stub("escalate_to_gary", args)
