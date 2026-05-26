"""Handlers for op-assistant-tools.

Phase E fills query_intent / fetch_wc_data / compose_reply. The remaining
side-effecting tools stay stubbed until Phase F.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from typing import Any


_WANNAVEG_REPO = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if _WANNAVEG_REPO not in sys.path:
    sys.path.insert(0, _WANNAVEG_REPO)

_HERMES_AGENT_REPO = os.environ.get(
    "HERMES_AGENT_REPO_PATH",
    os.path.expanduser("~/.hermes/hermes-agent"),
)
if os.path.isdir(_HERMES_AGENT_REPO) and _HERMES_AGENT_REPO not in sys.path:
    sys.path.insert(0, _HERMES_AGENT_REPO)


INTENT_ENUM = {
    "availability",
    "historical",
    "aggregate",
    "help",
    "price_edit_refuse",
    "unknown",
}


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _stub(tool_name: str, args: dict) -> str:
    return _json_dumps(
        {
            "status": "stub",
            "tool": tool_name,
            "args": args,
            "note": "Phase E/F will fill real logic.",
        },
    )


def _external_intent_from_parsed(parsed: Any) -> str:
    from wannavegtour.query_parser import QueryIntent

    if parsed.intent == QueryIntent.AVAILABILITY_CHECK:
        return "availability"
    if parsed.intent == QueryIntent.HISTORICAL_LOOKUP:
        return "aggregate" if (parsed.extras or {}).get("is_aggregate") else "historical"
    if parsed.intent == QueryIntent.PRICE_EDIT_HINT:
        return "price_edit_refuse"
    return "unknown"


def _entities_from_parsed(parsed: Any) -> dict[str, Any]:
    entities = {
        "raw_text": parsed.raw_text,
        "month": parsed.month,
        "day": parsed.day,
        "destination_hint": parsed.destination_hint,
        "matched_year": parsed.matched_year,
        "departure_date_mmdd": parsed.departure_date_mmdd,
        "departure_date_full": parsed.departure_date_full,
        "extras": parsed.extras or {},
    }
    # Compatibility aliases for the harness spec and LLM fallback shape.
    entities["tour_keyword"] = parsed.destination_hint
    if parsed.month and parsed.day:
        entities["date_hint"] = f"{parsed.month}/{parsed.day}"
    elif parsed.month:
        entities["date_hint"] = f"{parsed.month}月"
    else:
        entities["date_hint"] = None
    return entities


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_llm_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def _parse_llm_classification(text: str) -> tuple[str | None, dict[str, Any], float]:
    text = (text or "").strip()
    if not text:
        return None, {}, 0.0
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, {}, 0.0

    intent = payload.get("intent")
    if intent not in INTENT_ENUM:
        return None, {}, 0.0
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        entities = {}
    confidence = _coerce_float(payload.get("confidence"), 0.5)
    confidence = max(0.0, min(1.0, confidence))
    return intent, entities, confidence


def _call_llm_for_intent(text: str) -> tuple[str | None, dict[str, Any], float]:
    from agent.auxiliary_client import call_llm

    system = (
        "You classify OP travel staff messages. Return only compact JSON. "
        "Allowed intent values: availability, historical, aggregate, help, "
        "price_edit_refuse, unknown. Extract only concrete entities present "
        "in the text: tour_keyword, destination_hint, month, day, date_hint, "
        "year_qualifier, lifecycle_hint. Do not answer the user."
    )
    user = (
        "Classify this Traditional Chinese OP message into exactly one allowed "
        f"intent and return JSON with intent, entities, confidence: {text}"
    )
    response = call_llm(
        task="op_assistant_intent",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=180,
        timeout=8,
    )
    return _parse_llm_classification(_extract_llm_text(response))


def query_intent(args: dict, **kwargs) -> str:
    text = str((args or {}).get("text", "")).strip()
    if not text:
        return _json_dumps(
            {
                "intent": "unknown",
                "confidence": 0.0,
                "entities": {},
                "source": "empty_input",
            }
        )

    try:
        from wannavegtour.query_parser import QueryIntent, parse_query

        parsed = parse_query(text)
        if parsed and parsed.intent != QueryIntent.UNCLEAR:
            return _json_dumps(
                {
                    "intent": _external_intent_from_parsed(parsed),
                    "entities": _entities_from_parsed(parsed),
                    "confidence": 1.0,
                    "source": "deterministic",
                }
            )
    except Exception:
        # Query parsing is a sensor, not a point of failure. Fall through to
        # the auxiliary classifier if the deterministic parser is unavailable.
        pass

    try:
        intent, entities, confidence = _call_llm_for_intent(text)
        if intent and confidence >= 0.5:
            entities.setdefault("raw_text", text)
            return _json_dumps(
                {
                    "intent": intent,
                    "entities": entities,
                    "confidence": confidence,
                    "source": "llm",
                }
            )
    except Exception as e:
        return _json_dumps(
            {
                "intent": "unknown",
                "confidence": 0.0,
                "entities": {},
                "source": "llm_error",
                "error": str(e)[:100],
            }
        )

    return _json_dumps(
        {
            "intent": "unknown",
            "confidence": 0.0,
            "entities": {},
            "source": "llm_low_confidence",
        }
    )


def _parsed_query_from_entities(intent: str, entities: dict[str, Any]) -> Any:
    from wannavegtour.query_parser import ParsedQuery, QueryIntent, parse_query

    entities = entities or {}
    raw_text = str(entities.get("raw_text") or entities.get("text") or "").strip()
    if raw_text:
        parsed = parse_query(raw_text)
        if parsed.intent != QueryIntent.UNCLEAR:
            return parsed

    extras = entities.get("extras") if isinstance(entities.get("extras"), dict) else {}
    if intent == "aggregate":
        query_intent = QueryIntent.HISTORICAL_LOOKUP
        extras = {**extras, "is_aggregate": True}
    elif intent == "historical":
        query_intent = QueryIntent.HISTORICAL_LOOKUP
    elif intent == "price_edit_refuse":
        query_intent = QueryIntent.PRICE_EDIT_HINT
    elif intent == "availability":
        query_intent = QueryIntent.AVAILABILITY_CHECK
    else:
        query_intent = QueryIntent.UNCLEAR

    month = entities.get("month")
    day = entities.get("day")
    matched_year = entities.get("matched_year")
    for key, value in (("month", month), ("day", day), ("matched_year", matched_year)):
        if value in (None, ""):
            continue
        try:
            if key == "month":
                month = int(value)
            elif key == "day":
                day = int(value)
            else:
                matched_year = int(value)
        except (TypeError, ValueError):
            if key == "month":
                month = None
            elif key == "day":
                day = None
            else:
                matched_year = None

    destination_hint = (
        entities.get("destination_hint")
        or entities.get("tour_keyword")
        or entities.get("keyword")
    )
    return ParsedQuery(
        raw_text=raw_text,
        intent=query_intent,
        month=month,
        day=day,
        destination_hint=str(destination_hint) if destination_hint else None,
        matched_year=matched_year,
        extras=extras,
    )


def _product_to_dict(product: Any) -> dict[str, Any]:
    return {field.name: getattr(product, field.name) for field in dataclasses.fields(product)}


def _serialize_query(query: Any) -> dict[str, Any]:
    return _entities_from_parsed(query)


def _serialize_check_result(result: Any) -> dict[str, Any]:
    return {
        "result_type": "availability_check",
        "kind": result.kind.value,
        "query": _serialize_query(result.query),
        "products": [_product_to_dict(p) for p in result.products],
        "advisory": list(result.advisory or []),
        "error_message": result.error_message,
        "found": bool(result.products),
    }


def _serialize_historical_result(result: Any) -> dict[str, Any]:
    return {
        "result_type": "historical_lookup",
        "kind": result.kind.value,
        "query": _serialize_query(result.query),
        "products": [_product_to_dict(p) for p in result.products],
        "advisory": list(result.advisory or []),
        "error_message": result.error_message,
        "extras": result.extras or {},
        "found": bool(result.products),
    }


def _wc_dry_run(args: dict[str, Any]) -> bool:
    value = (args or {}).get("dry_run")
    if value is None:
        value = os.environ.get("OP_ASSISTANT_WC_DRY_RUN")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _make_wc_client(args: dict[str, Any]) -> Any:
    if _wc_dry_run(args):
        raise RuntimeError("WooCommerce dry-run mode is enabled")
    from wannavegtour.config import credential_path_for_env, load_config
    from wannavegtour.wc_client import WCClient

    return WCClient(load_config(credential_path_for_env()))


def fetch_wc_data(args: dict, **kwargs) -> str:
    args = args or {}
    intent = args.get("intent")
    entities = args.get("entities") if isinstance(args.get("entities"), dict) else {}

    if intent == "help":
        return _json_dumps(
            {
                "data": {
                    "help_text": "可以查團、查歷史成團/額滿、查熱門排行；改價或修改資料請 Gary/OP 手動處理。"
                },
                "intent": "help",
                "source": "static",
            }
        )
    if intent == "price_edit_refuse":
        return _json_dumps(
            {
                "data": {"refusal": True},
                "intent": "price_edit_refuse",
                "source": "policy",
            }
        )
    if intent == "unknown":
        return _json_dumps(
            {
                "data": None,
                "intent": "unknown",
                "source": "no_fetcher",
                "reason": "no fetcher for unknown intent",
            }
        )

    if intent == "availability":
        try:
            from wannavegtour.availability_checker import AvailabilityChecker, CheckResultKind

            result = AvailabilityChecker(_make_wc_client(args)).check(
                _parsed_query_from_entities(intent, entities)
            )
            if result.kind == CheckResultKind.ERROR:
                return _json_dumps(
                    {
                        "data": None,
                        "intent": intent,
                        "error": result.error_message or "WooCommerce unavailable",
                        "fallback": None,
                    }
                )
            return _json_dumps(
                {
                    "data": _serialize_check_result(result),
                    "intent": intent,
                    "source": "wc_live",
                }
            )
        except Exception as e:
            return _json_dumps(
                {"data": None, "intent": intent, "error": str(e)[:200], "fallback": None}
            )

    if intent in {"historical", "aggregate"}:
        try:
            from wannavegtour.historical_lookup import HistoricalLookup, HistoricalLookupKind

            result = HistoricalLookup(_make_wc_client(args)).lookup(
                _parsed_query_from_entities(intent, entities)
            )
            if result.kind == HistoricalLookupKind.ERROR:
                return _json_dumps(
                    {
                        "data": None,
                        "intent": intent,
                        "error": result.error_message or "WooCommerce unavailable",
                        "fallback": None,
                    }
                )
            return _json_dumps(
                {
                    "data": _serialize_historical_result(result),
                    "intent": intent,
                    "source": "wc_live",
                }
            )
        except Exception as e:
            return _json_dumps(
                {"data": None, "intent": intent, "error": str(e)[:200], "fallback": None}
            )

    return _json_dumps({"error": f"unrecognized intent: {intent}"})


def _product_from_dict(payload: dict[str, Any]) -> Any:
    from wannavegtour.wc_client import WCProduct

    allowed = {field.name for field in dataclasses.fields(WCProduct)}
    return WCProduct(**{k: payload.get(k) for k in allowed})


def _check_result_from_data(data: dict[str, Any]) -> Any:
    from wannavegtour.availability_checker import CheckResult, CheckResultKind

    query = _parsed_query_from_entities("availability", data.get("query") or {})
    products = [_product_from_dict(p) for p in data.get("products") or []]
    return CheckResult(
        kind=CheckResultKind(data["kind"]),
        query=query,
        products=products,
        advisory=list(data.get("advisory") or []),
        error_message=data.get("error_message"),
    )


def _historical_result_from_data(data: dict[str, Any]) -> Any:
    from wannavegtour.historical_lookup import HistoricalLookupKind, HistoricalResult

    query = _parsed_query_from_entities("historical", data.get("query") or {})
    products = [_product_from_dict(p) for p in data.get("products") or []]
    return HistoricalResult(
        kind=HistoricalLookupKind(data["kind"]),
        query=query,
        products=products,
        advisory=list(data.get("advisory") or []),
        error_message=data.get("error_message"),
        extras=data.get("extras") or {},
    )


def _normal_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = data.get("data")
    if isinstance(nested, dict) and "result_type" not in data:
        return nested
    return data


def _template_reply(intent: str, data: dict[str, Any]) -> str | None:
    payload = _normal_data(data)
    if intent == "availability" and payload.get("result_type") == "availability_check":
        from wannavegtour.response_formatter import format_response

        return format_response(_check_result_from_data(payload))
    if intent in {"historical", "aggregate"} and payload.get("result_type") == "historical_lookup":
        from wannavegtour.response_formatter import format_historical

        return format_historical(_historical_result_from_data(payload))
    if intent == "help":
        help_text = payload.get("help_text") or "可以查團、查歷史成團/額滿、查熱門排行。"
        return str(help_text)
    if intent == "price_edit_refuse" and payload.get("refusal"):
        return "這看起來是改價或修改資料指令；小弟目前只查詢不改資料，請 OP/Gary 手動處理。"
    if intent == "unknown":
        return "這題我判斷不出要查什麼，請補目的地、日期，或改問查團/歷史/熱門。"
    if data.get("error"):
        return "WooCommerce 目前查詢失敗，請稍後再試或請 Gary 手動確認。"
    return None


def compose_reply(args: dict, **kwargs) -> str:
    args = args or {}
    intent = args.get("intent")
    data = args.get("data") if isinstance(args.get("data"), dict) else {}

    try:
        draft = _template_reply(intent, data)
        if draft:
            return _json_dumps({"draft_reply_body": draft, "source": "template"})
    except Exception:
        pass

    try:
        from agent.auxiliary_client import call_llm

        prompt_data = json.dumps(data, ensure_ascii=False, default=_json_default)
        response = call_llm(
            task="op_assistant_compose",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write only a short Traditional Chinese LINE reply body "
                        "for OP travel staff. No greeting, no prefix, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"intent={intent}; data={prompt_data}. Keep under 150 "
                        "Traditional Chinese characters."
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=180,
            timeout=8,
        )
        draft = _extract_llm_text(response).strip()
        return _json_dumps({"draft_reply_body": draft, "source": "llm"})
    except Exception as e:
        return _json_dumps(
            {"draft_reply_body": "", "source": "error", "error": str(e)[:200]}
        )


def validate_reply(args: dict, **kwargs) -> str:
    return _stub("validate_reply", args)


def send_reply(args: dict, **kwargs) -> str:
    return _stub("send_reply", args)


def escalate_to_gary(args: dict, **kwargs) -> str:
    return _stub("escalate_to_gary", args)
