"""wannavegtour: AI-Native Company first business slice (Type 1: availability check).

Reads internal OP-group LINE messages (later — currently CLI-driven), extracts
a departure date + destination, looks up WooCommerce stock, returns LINE-friendly
answer. No writes. No LLM in the control flow (Code is Law).
"""

from .config import WCConfig, load_config
from .wc_client import WCClient, WCProduct
from .query_parser import ParsedQuery, QueryIntent, parse_query
from .availability_checker import AvailabilityChecker, CheckResult, CheckResultKind
from .historical_lookup import HistoricalLookup, HistoricalResult, HistoricalLookupKind
from .response_formatter import format_response, format_historical

__all__ = [
    "WCConfig",
    "load_config",
    "WCClient",
    "WCProduct",
    "ParsedQuery",
    "QueryIntent",
    "parse_query",
    "AvailabilityChecker",
    "CheckResult",
    "CheckResultKind",
    "HistoricalLookup",
    "HistoricalResult",
    "HistoricalLookupKind",
    "format_response",
    "format_historical",
]
