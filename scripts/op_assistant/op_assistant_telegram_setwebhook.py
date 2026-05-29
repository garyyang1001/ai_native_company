"""Register / verify the Telegram Bot webhook for telegram-op-control.

V0.3 Phase 1 ops script. Not a runtime plugin — run manually after setting
TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / TELEGRAM_PUBLIC_URL.

Reads creds from:

* ``~/.hermes/profiles/${HERMES_PROFILE:-op-assistant}/.env`` then
* ``~/.hermes/.env``

Calls Telegram Bot API ``setWebhook`` with:

* ``url = ${TELEGRAM_PUBLIC_URL}/telegram/webhook``
* ``secret_token = ${TELEGRAM_WEBHOOK_SECRET}``
* ``allowed_updates = ["message", "callback_query", "edited_message"]``
* ``drop_pending_updates = True``

Then calls ``getWebhookInfo`` and pretty-prints the result.

Usage::

    /home/wannavegtour/.hermes/hermes-agent/venv/bin/python \\
        scripts/op_assistant/op_assistant_telegram_setwebhook.py
    # add --dry-run to skip the actual setWebhook call
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests


# Bot tokens are baked into the Telegram API URL ("/bot<TOKEN>/setWebhook"),
# so any exception that prints the URL (including default `requests` traceback)
# would leak the token. We always go through this sanitizer before printing.
_TOKEN_URL_RE = re.compile(r"/bot[^/]+/")


def _sanitize(s: str) -> str:
    return _TOKEN_URL_RE.sub("/bot<REDACTED>/", s)


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
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    _load_env_file(Path.home() / ".hermes" / "profiles" / profile / ".env")
    _load_env_file(Path.home() / ".hermes" / ".env")


def _set_webhook(token: str, url: str, secret: str) -> dict:
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    try:
        r = requests.post(api, json={
            "url": url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query", "edited_message"],
            "drop_pending_updates": True,
            "max_connections": 40,
        }, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        # `raise from None` drops the chained traceback so the unsanitized
        # URL in `requests.exceptions.HTTPError(...)` never reaches stderr.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise RuntimeError(
            f"setWebhook failed: status={status} type={type(exc).__name__}"
        ) from None


def _get_webhook_info(token: str) -> dict:
    api = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    try:
        r = requests.get(api, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise RuntimeError(
            f"getWebhookInfo failed: status={status} type={type(exc).__name__}"
        ) from None


def _delete_webhook(token: str) -> dict:
    api = f"https://api.telegram.org/bot{token}/deleteWebhook"
    try:
        r = requests.post(api, json={"drop_pending_updates": True}, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise RuntimeError(
            f"deleteWebhook failed: status={status} type={type(exc).__name__}"
        ) from None


def _print_info(token: str) -> int:
    try:
        info = _get_webhook_info(token)
    except RuntimeError as exc:
        print(_sanitize(str(exc)), file=sys.stderr)
        return 1
    info_view = info.get("result", info)
    print("getWebhookInfo:")
    print(_sanitize(json.dumps(info_view, ensure_ascii=False, indent=2)))
    return 0


def run(dry_run: bool = False,
        delete: bool = False,
        verify_only: bool = False) -> int:
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not token:
        print("missing env: TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2

    # --verify-only / --delete only need the token, not the public URL.
    if verify_only:
        return _print_info(token)

    if delete:
        try:
            result = _delete_webhook(token)
        except RuntimeError as exc:
            print(_sanitize(str(exc)), file=sys.stderr)
            return 1
        if not result.get("ok"):
            print(_sanitize(
                f"deleteWebhook failed: {json.dumps(result, ensure_ascii=False)}"
            ), file=sys.stderr)
            return 1
        print(f"deleteWebhook ok: {result.get('description')}")
        return _print_info(token)

    # Default path: set webhook. Requires secret + public URL.
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    public_url = os.environ.get("TELEGRAM_PUBLIC_URL", "").rstrip("/")
    missing = [k for k, v in [
        ("TELEGRAM_WEBHOOK_SECRET", secret),
        ("TELEGRAM_PUBLIC_URL", public_url),
    ] if not v]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2

    webhook_url = f"{public_url}/telegram/webhook"
    print(f"target webhook url: {webhook_url}")

    if dry_run:
        print("--dry-run: skipping setWebhook call")
    else:
        try:
            result = _set_webhook(token, webhook_url, secret)
        except RuntimeError as exc:
            print(_sanitize(str(exc)), file=sys.stderr)
            return 1
        if not result.get("ok"):
            print(_sanitize(
                f"setWebhook failed: {json.dumps(result, ensure_ascii=False)}"
            ), file=sys.stderr)
            return 1
        print(f"setWebhook ok: {result.get('description')}")

    return _print_info(token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="skip setWebhook call, still print getWebhookInfo")
    g.add_argument(
        "--delete", action="store_true",
        help="call deleteWebhook (drop_pending_updates=true) — use before "
             "rotating the secret, then re-run without --delete"
    )
    g.add_argument(
        "--verify-only", action="store_true",
        help="only print getWebhookInfo, no setWebhook/deleteWebhook"
    )
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run, delete=args.delete,
                 verify_only=args.verify_only))


if __name__ == "__main__":
    main()
