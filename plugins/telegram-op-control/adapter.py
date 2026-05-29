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

import asyncio
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
    """Two-phase in-memory ``update_id`` dedupe with TTL.

    Codex xhigh review #1: we cannot mark an update as deduped *before* the
    durable write succeeds. If we did, a writer crash would leave a pending
    dedupe bit and the Telegram retry would be silently discarded — the
    inbound event would be lost forever. So entries are written ``pending``
    on ``begin()`` and promoted to ``committed`` only after ``commit()``.
    A failed handler calls ``rollback()`` so the retry can re-process.

    Restart-clean (Karpathy 2 Phase 1 simplicity); Phase 4 moves this into
    a PostgreSQL unique-index claim (V0.3 R10/R11).
    """

    _STATE_PENDING = "pending"
    _STATE_COMMITTED = "committed"

    def __init__(self, ttl_seconds: int = DEDUPE_TTL_SECONDS,
                 max_entries: int = DEDUPE_MAX_ENTRIES) -> None:
        # value = (mono_timestamp, state)
        self._seen: dict[int, tuple[float, str]] = {}
        self._ttl = ttl_seconds
        self._max = max_entries

    def begin(self, update_id: int) -> bool:
        """Return True if ``update_id`` was already seen (pending or
        committed) within TTL. Otherwise mark it pending and return False.
        """
        now = time.monotonic()
        if len(self._seen) > self._max:
            self._gc(now)
        existing = self._seen.get(update_id)
        if existing is not None and (now - existing[0]) < self._ttl:
            return True
        self._seen[update_id] = (now, self._STATE_PENDING)
        return False

    def commit(self, update_id: int) -> None:
        """Promote ``update_id`` from pending to committed."""
        self._seen[update_id] = (time.monotonic(), self._STATE_COMMITTED)

    def rollback(self, update_id: int) -> None:
        """Drop a pending mark so a retry can re-process. No-op if the
        entry is already committed (durable write already succeeded; the
        retry should see duplicate)."""
        existing = self._seen.get(update_id)
        if existing is not None and existing[1] == self._STATE_PENDING:
            self._seen.pop(update_id, None)

    def _gc(self, now: float) -> None:
        cutoff = now - self._ttl
        self._seen = {k: v for k, v in self._seen.items() if v[0] > cutoff}


# --- chat / actor extraction (deterministic dispatcher, no LLM) -------------

def _safe_dict(value: Any) -> dict[str, Any]:
    """Codex xhigh review #2: defend every nesting level against forged
    non-dict shapes (``{"message": "x"}`` or ``{"callback_query": []}``).
    A signed request can still carry malformed JSON — wrong types must
    produce an audit-logged 400, not a 500.
    """
    return value if isinstance(value, dict) else {}


def extract_chat_id(update: dict[str, Any]) -> tuple[str | None, str]:
    """Return ``(effective_chat_id, kind)`` from a Telegram update.

    Deterministic dispatch over the three update kinds we expect:
    ``message``, ``callback_query``, ``edited_message``. Anything else,
    or any layer that isn't actually a dict, returns ``(None, kind)``
    so the caller can audit-log and reject.

    No LLM. No fallback heuristics. If Telegram introduces a new update
    shape we treat it as malformed until a later phase adds support.
    """
    if "message" in update:
        chat = _safe_dict(_safe_dict(update.get("message")).get("chat"))
        return (str(chat["id"]) if "id" in chat else None, "message")
    if "callback_query" in update:
        cb = _safe_dict(update.get("callback_query"))
        chat = _safe_dict(_safe_dict(cb.get("message")).get("chat"))
        return (str(chat["id"]) if "id" in chat else None, "callback_query")
    if "edited_message" in update:
        chat = _safe_dict(_safe_dict(update.get("edited_message")).get("chat"))
        return (str(chat["id"]) if "id" in chat else None, "edited_message")
    return None, "unknown"


def extract_actor_user_id(update: dict[str, Any]) -> str | None:
    """Return the effective acting user_id from a Telegram update.

    Codex xhigh review #4: ``chat_id`` is not enough for Phase 4 action
    authorization — a group chat (whose chat_id might be on the
    allowlist for daily summaries) does **not** mean every member is
    allowed to press KILL. We record the actor user_id at inbound so the
    Phase 4 dispatcher can apply an action-level user allowlist without
    re-parsing the raw update.
    """
    for key in ("message", "callback_query", "edited_message"):
        if key not in update:
            continue
        from_user = _safe_dict(_safe_dict(update.get(key)).get("from"))
        if "id" in from_user:
            return str(from_user["id"])
    return None


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

    Order (post codex review 2026-05-29):

    1. Signature verify (else 401 + audit ``telegram_unauthorized``).
    2. Body size cap (else 413).
    3. JSON parse (else 400 + audit ``telegram_malformed``).
    4. ``update_id`` presence (else 400 + audit ``telegram_malformed``).
    5. Chat extraction (unknown shape => 400 + audit ``telegram_malformed``).
    6. Allowlist check (else 403 + audit ``telegram_rejected_chat``).
    7. Dedupe by ``update_id`` — *after* allowlist so unauthorized retries
       always audit, never get silently swallowed (codex C3).
    8. Happy path => 200 OK + ``telegram_inbound`` row.

    All writes go through ``asyncio.to_thread`` so a slow / blocked Postgres
    cannot stall the aiohttp event loop past Telegram's 5 s timeout (codex B1).
    """
    config: AdapterConfig = request.app["config"]
    dedupe: UpdateIdDedupe = request.app["dedupe"]
    writer = request.app["writer"]

    # We deliberately do *not* trust X-Forwarded-For — without an explicit
    # trusted-proxy contract any caller can forge it. request.remote is the
    # connection peer, which is what we actually audit (codex A4).
    remote_ip = request.remote or "unknown"

    def _audit(event_type: str, payload: dict[str, Any]) -> Any:
        """Run the (sync) writer.write off-loop so DB latency cannot stall us."""
        return asyncio.to_thread(writer.write, event_type, payload)

    # 1. Signature verify
    received_token = request.headers.get(SECRET_TOKEN_HEADER, "")
    if not hmac.compare_digest(received_token, config.webhook_secret):
        # Never echo the received token or the expected secret.
        await _audit(EVENT_TELEGRAM_UNAUTHORIZED, {
            "remote_ip": remote_ip,
            "path": request.path,
            "received_token_len": len(received_token),
        })
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Body size cap
    if request.content_length is not None and request.content_length > BODY_MAX_BYTES:
        return web.json_response({"error": "body too large"}, status=413)

    body = await request.read()
    body_bytes = len(body)
    if body_bytes > BODY_MAX_BYTES:
        return web.json_response({"error": "body too large"}, status=413)

    # 3. JSON parse
    try:
        update = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        await _audit(EVENT_TELEGRAM_MALFORMED, {
            "reason": "json_or_utf8_decode_failed",
            "error_type": type(exc).__name__,
            "remote_ip": remote_ip,
            "body_bytes": body_bytes,
        })
        return web.json_response({"error": "malformed"}, status=400)

    if not isinstance(update, dict):
        await _audit(EVENT_TELEGRAM_MALFORMED, {
            "reason": "update_not_object",
            "remote_ip": remote_ip,
            "body_bytes": body_bytes,
        })
        return web.json_response({"error": "update not object"}, status=400)

    # 4. update_id presence
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        await _audit(EVENT_TELEGRAM_MALFORMED, {
            "reason": "missing_or_non_int_update_id",
            "update_keys": list(update.keys())[:10],
            "remote_ip": remote_ip,
        })
        return web.json_response({"error": "missing update_id"}, status=400)

    # 5. Chat extraction
    chat_id, kind = extract_chat_id(update)
    if chat_id is None:
        await _audit(EVENT_TELEGRAM_MALFORMED, {
            "reason": "no_extractable_chat_id",
            "update_kind": kind,
            "update_id": update_id,
            "update_keys": list(update.keys())[:10],
        })
        return web.json_response({"error": "unknown update shape"}, status=400)

    # 6. Allowlist check — fail-closed when allowlist is empty.
    # Done BEFORE dedupe so unauthorized retries always leave an audit row
    # (otherwise the first reject sets the dedupe bit and silences the rest).
    if not config.allowed_chats or chat_id not in config.allowed_chats:
        await _audit(EVENT_TELEGRAM_REJECTED_CHAT, {
            "update_id": update_id,
            "chat_id_suffix": chat_id[-4:],   # debug-only suffix, never full id
            "update_kind": kind,
        })
        return web.json_response({"error": "chat not allowed"}, status=403)

    # 7. Dedupe (begin pending) — only for *allowed* updates. The mark is
    # only promoted to committed after the durable write succeeds, so a
    # writer crash leaves NO dedupe state and the Telegram retry will be
    # processed (codex xhigh review #1).
    if dedupe.begin(update_id):
        return web.json_response({"status": "duplicate"}, status=200)

    # 8. Happy path — record the inbound update, then commit the dedupe.
    try:
        await _audit(EVENT_TELEGRAM_INBOUND, {
            "update_id": update_id,
            "effective_chat_id": chat_id,
            "actor_user_id": extract_actor_user_id(update),
            "kind": kind,
            "raw_update": update,
        })
    except Exception:
        dedupe.rollback(update_id)
        raise
    dedupe.commit(update_id)
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
