"""Telegram Bot inbound webhook for OP Assistant V0.3 control plane.

V0.3 Phase 1 — standalone aiohttp service, NOT a Hermes platform plugin.

Scope of THIS file (Phase 1):

* POST ``/telegram/webhook``
* Verify ``X-Telegram-Bot-Api-Secret-Token`` header (``hmac.compare_digest``).
* Dedupe by ``update_id`` (in-memory dict + 24hr TTL — Telegram retry
  window is ~minutes; restart-on-clean-cache is acceptable here).
* Enforce a ``chat_id`` allowlist (``TELEGRAM_ALLOWED_CHATS``,
  fail-closed: empty = reject all).
* Persist a ``telegram_inbound`` (or ``telegram_unauthorized`` /
  ``telegram_rejected_chat`` / ``telegram_malformed``) row to
  ``op_assistant_kernel.events``.

NOT in Phase 1 scope (handled later):

* Inline keyboard *send* — Phase 3, in ``daily_curate``.
* Callback dispatch (apv / rej / vw / kill) — Phase 4.
* Approval audit chain — Phase 5.

Run standalone::

    HERMES_PROFILE=op-assistant \\
    /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
    plugins/telegram-op-control/adapter.py

Code-is-Rule: every dispatch decision below is deterministic Python.
There is no LLM import in this file.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

logger = logging.getLogger("hermes_plugins.telegram_op_control.adapter")


# --- env loading ------------------------------------------------------------

def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _load_env() -> None:
    """Load Hermes profile + Hermes home env files (idempotent)."""
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    _load_env_file(Path.home() / ".hermes" / "profiles" / profile / ".env")
    _load_env_file(Path.home() / ".hermes" / ".env")


# --- repo path so closed_loop_kernel imports work ---------------------------

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)


# --- constants --------------------------------------------------------------

DEFAULT_WEBHOOK_PORT = 8647        # op-assistant-line uses 8646
DEFAULT_WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PATH = "/telegram/webhook"
HEALTH_PATH = "/health"
SECRET_TOKEN_HEADER = "X-Telegram-Bot-Api-Secret-Token"

BODY_MAX_BYTES = 1_048_576         # 1 MiB — Telegram updates are tiny JSON
DEDUPE_TTL_SECONDS = 86_400        # 24hr
DEDUPE_MAX_ENTRIES = 100_000       # safety cap before lazy GC

EVENT_TELEGRAM_INBOUND = "telegram_inbound"
EVENT_TELEGRAM_UNAUTHORIZED = "telegram_unauthorized"
EVENT_TELEGRAM_REJECTED_CHAT = "telegram_rejected_chat"
EVENT_TELEGRAM_MALFORMED = "telegram_malformed"


# --- dedupe cache -----------------------------------------------------------

class UpdateIdDedupe:
    """In-memory ``update_id`` dedupe with TTL.

    Phase 1 simplicity (Karpathy 2): not persisted. Restart = clean cache.
    Telegram only retries failed deliveries for a few minutes, so a TTL of
    24hr is overkill but cheap. Lazy GC at every check once the dict grows
    past ``max_entries``.
    """

    def __init__(self, ttl_seconds: int = DEDUPE_TTL_SECONDS,
                 max_entries: int = DEDUPE_MAX_ENTRIES) -> None:
        self._seen: dict[int, float] = {}
        self._ttl = ttl_seconds
        self._max = max_entries

    def seen_then_mark(self, update_id: int) -> bool:
        """Return True if ``update_id`` was already seen within TTL."""
        now = time.monotonic()
        if len(self._seen) > self._max:
            self._gc(now)
        existing = self._seen.get(update_id)
        if existing is not None and (now - existing) < self._ttl:
            return True
        self._seen[update_id] = now
        return False

    def _gc(self, now: float) -> None:
        cutoff = now - self._ttl
        self._seen = {k: t for k, t in self._seen.items() if t > cutoff}


# --- chat extraction (deterministic dispatcher, no LLM) ---------------------

def extract_chat_id(update: dict[str, Any]) -> tuple[str | None, str]:
    """Return (effective_chat_id, kind) from a Telegram update.

    Deterministic dispatch over the three update kinds we expect:
    ``message``, ``callback_query``, ``edited_message``. Anything else
    returns ``(None, "unknown")`` so the caller can audit-log and reject.

    No LLM. No fallback heuristics. If Telegram introduces a new update
    shape we treat it as malformed until V0.x adds explicit support.
    """
    if "message" in update:
        chat = (update["message"] or {}).get("chat") or {}
        return (str(chat["id"]) if "id" in chat else None, "message")
    if "callback_query" in update:
        msg = (update["callback_query"] or {}).get("message") or {}
        chat = msg.get("chat") or {}
        return (str(chat["id"]) if "id" in chat else None, "callback_query")
    if "edited_message" in update:
        chat = (update["edited_message"] or {}).get("chat") or {}
        return (str(chat["id"]) if "id" in chat else None, "edited_message")
    return None, "unknown"


# --- config -----------------------------------------------------------------

class AdapterConfig:
    """Validated configuration loaded from env."""

    def __init__(self,
                 webhook_secret: str,
                 allowed_chats: frozenset[str],
                 kernel_url: str | None = None,
                 host: str = DEFAULT_WEBHOOK_HOST,
                 port: int = DEFAULT_WEBHOOK_PORT) -> None:
        if not webhook_secret:
            raise ValueError(
                "TELEGRAM_WEBHOOK_SECRET is required (random 32+ char token; "
                "must match Telegram setWebhook secret_token)"
            )
        self.webhook_secret = webhook_secret
        self.allowed_chats = allowed_chats
        self.kernel_url = kernel_url
        self.host = host
        self.port = port

    @classmethod
    def from_env(cls) -> "AdapterConfig":
        _load_env()
        chats_raw = os.environ.get("TELEGRAM_ALLOWED_CHATS", "")
        allowed = frozenset(s.strip() for s in chats_raw.split(",") if s.strip())
        return cls(
            webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
            allowed_chats=allowed,
            kernel_url=os.environ.get("KERNEL_DATABASE_URL"),
            host=os.environ.get("TELEGRAM_WEBHOOK_HOST", DEFAULT_WEBHOOK_HOST),
            port=int(os.environ.get("TELEGRAM_WEBHOOK_PORT",
                                    str(DEFAULT_WEBHOOK_PORT))),
        )


# --- event writer -----------------------------------------------------------

class EventWriter:
    """Wrap KernelStore so unit tests can substitute a fake writer."""

    def __init__(self, kernel_url: str) -> None:
        # Deferred kernel import keeps the module importable without psycopg
        # (tests inject FakeWriter and never touch KernelStore).
        from closed_loop_kernel.store import KernelStore, json_param  # noqa: WPS433

        self._store = KernelStore.from_url(kernel_url)
        self._json_param = json_param

    def write(self, event_type: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        self._store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                event_id,
                event_type,
                self._json_param(payload),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return event_id

    def close(self) -> None:
        self._store.close()


# --- webhook handler --------------------------------------------------------

async def webhook_handler(request: web.Request) -> web.Response:
    """POST /telegram/webhook — single deterministic pipeline.

    Order matters:

    1. Signature verify (else 401 + audit ``telegram_unauthorized``).
    2. Body size cap (else 413).
    3. JSON parse (else 400 + audit ``telegram_malformed``).
    4. ``update_id`` presence (else 400 + audit ``telegram_malformed``).
    5. Dedupe by ``update_id`` (duplicate => 200 OK, no new row — Telegram
       retries should look like success on our end).
    6. Chat extraction (unknown shape => 400 + audit ``telegram_malformed``).
    7. Allowlist check (else 403 + audit ``telegram_rejected_chat``).
    8. Happy path => 200 OK + ``telegram_inbound`` row.
    """
    config: AdapterConfig = request.app["config"]
    dedupe: UpdateIdDedupe = request.app["dedupe"]
    writer = request.app["writer"]

    remote_ip = request.headers.get(
        "X-Forwarded-For", request.remote or "unknown",
    )

    # 1. Signature verify
    received_token = request.headers.get(SECRET_TOKEN_HEADER, "")
    if not hmac.compare_digest(received_token, config.webhook_secret):
        # Never echo the received token or the expected secret.
        writer.write(EVENT_TELEGRAM_UNAUTHORIZED, {
            "remote_ip": remote_ip,
            "path": request.path,
            "received_token_len": len(received_token),
        })
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Body size cap
    if request.content_length is not None and request.content_length > BODY_MAX_BYTES:
        return web.json_response({"error": "body too large"}, status=413)

    body = await request.read()
    if len(body) > BODY_MAX_BYTES:
        return web.json_response({"error": "body too large"}, status=413)

    # 3. JSON parse
    try:
        update = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        writer.write(EVENT_TELEGRAM_MALFORMED, {
            "reason": "json_or_utf8_decode_failed",
            "error_type": type(exc).__name__,
            "remote_ip": remote_ip,
        })
        return web.json_response({"error": "malformed"}, status=400)

    if not isinstance(update, dict):
        writer.write(EVENT_TELEGRAM_MALFORMED, {
            "reason": "update_not_object",
            "remote_ip": remote_ip,
        })
        return web.json_response({"error": "update not object"}, status=400)

    # 4. update_id presence
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        writer.write(EVENT_TELEGRAM_MALFORMED, {
            "reason": "missing_or_non_int_update_id",
            "update_keys": list(update.keys())[:10],
            "remote_ip": remote_ip,
        })
        return web.json_response({"error": "missing update_id"}, status=400)

    # 5. Dedupe — Telegram retries should look like success on our end.
    if dedupe.seen_then_mark(update_id):
        return web.json_response({"status": "duplicate"}, status=200)

    # 6. Chat extraction
    chat_id, kind = extract_chat_id(update)
    if chat_id is None:
        writer.write(EVENT_TELEGRAM_MALFORMED, {
            "reason": "no_extractable_chat_id",
            "update_kind": kind,
            "update_id": update_id,
            "update_keys": list(update.keys())[:10],
        })
        return web.json_response({"error": "unknown update shape"}, status=400)

    # 7. Allowlist check — fail-closed when allowlist is empty.
    if not config.allowed_chats or chat_id not in config.allowed_chats:
        writer.write(EVENT_TELEGRAM_REJECTED_CHAT, {
            "update_id": update_id,
            "chat_id_suffix": chat_id[-4:],   # debug-only suffix, never full id
            "update_kind": kind,
        })
        return web.json_response({"error": "chat not allowed"}, status=403)

    # 8. Happy path — record the inbound update.
    writer.write(EVENT_TELEGRAM_INBOUND, {
        "update_id": update_id,
        "effective_chat_id": chat_id,
        "kind": kind,
        "raw_update": update,
    })
    return web.json_response({"status": "ok"}, status=200)


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# --- app factory ------------------------------------------------------------

def create_app(config: AdapterConfig,
               writer: Any = None,
               dedupe: UpdateIdDedupe | None = None) -> web.Application:
    """Build the aiohttp app. ``writer`` / ``dedupe`` are injectable so tests
    can substitute fakes without touching the kernel.
    """
    app = web.Application(client_max_size=BODY_MAX_BYTES)
    app["config"] = config
    app["dedupe"] = dedupe or UpdateIdDedupe()
    if writer is None:
        if not config.kernel_url:
            raise RuntimeError(
                "KERNEL_DATABASE_URL not set; cannot create event writer"
            )
        writer = EventWriter(config.kernel_url)
    app["writer"] = writer
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    app.router.add_get(HEALTH_PATH, health_handler)
    return app


# --- standalone runner ------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = AdapterConfig.from_env()
    app = create_app(config)
    logger.info(
        "telegram-op-control starting on %s:%d allowlist_size=%d",
        config.host, config.port, len(config.allowed_chats),
    )
    web.run_app(app, host=config.host, port=config.port, access_log=logger)


if __name__ == "__main__":
    main()
