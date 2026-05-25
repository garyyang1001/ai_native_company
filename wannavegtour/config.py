"""Credential loading for wannavegtour WC REST API.

Reads ~/.hermes/credentials/wannavegtour/wc-api.json (mode 600).
File schema mirrors what the user filled by hand; field names are kept generic
("consumer_key" / "consumer_secret") even though the actual mechanism is WP
Application Password (BasicAuth user + app-password). WC REST endpoints accept
both auth styles; the wire format is identical.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CREDENTIAL_PATH = Path.home() / ".hermes" / "credentials" / "wannavegtour" / "wc-api.json"

# Maximum permissive mode bits allowed on the credential file.
# 0o600 = owner read/write only. Any group/world bits trip the fail-closed check.
_MAX_PERMISSIVE_MODE = 0o600


@dataclass(frozen=True)
class WCConfig:
    site: str
    base_url: str
    api_namespace: str
    consumer_key: str
    consumer_secret: str
    permissions: str

    @property
    def api_root(self) -> str:
        return f"{self.base_url.rstrip('/')}/wp-json/{self.api_namespace}"


class CredentialError(RuntimeError):
    """Raised when credentials are missing, unfilled, or malformed."""


def load_config(path: Path | str | None = None, *, allow_loose_perms: bool = False) -> WCConfig:
    """Load WCConfig from a JSON file. Defaults to DEFAULT_CREDENTIAL_PATH.

    Fail-closed on insecure file permissions: file must be mode 0o600 or stricter.
    Set allow_loose_perms=True to bypass (used by tests where temp files inherit
    umask). Windows is exempt since POSIX-style mode bits don't apply.

    Raises CredentialError when the file is missing, unreadable, has group/world
    bits set, is JSON-invalid, contains a placeholder value, or lacks required
    fields.
    """
    p = Path(path) if path else DEFAULT_CREDENTIAL_PATH
    if not p.exists():
        raise CredentialError(f"credential file not found: {p}")

    # Permission check — fail closed if other principals can read the secret.
    if not allow_loose_perms and os.name == "posix":
        try:
            mode_bits = stat.S_IMODE(p.stat().st_mode)
        except OSError as e:
            raise CredentialError(f"cannot stat credential file: {p}: {e}") from e
        if mode_bits & ~_MAX_PERMISSIVE_MODE:
            raise CredentialError(
                f"credential file {p} has mode {oct(mode_bits)} "
                f"(other principals can read it). Required: 0o600 or stricter. "
                f"Fix: chmod 600 {p}"
            )

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CredentialError(f"credential file is not valid JSON: {p}: {e}") from e

    required = ("base_url", "consumer_key", "consumer_secret")
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise CredentialError(f"credential file missing keys: {missing} in {p}")

    if raw["consumer_key"].startswith("REPLACE_WITH_") or raw["consumer_secret"].startswith("REPLACE_WITH_"):
        raise CredentialError(
            f"credential file contains placeholder values; replace them in {p}"
        )

    return WCConfig(
        site=raw.get("site", "wannavegtour"),
        base_url=raw["base_url"],
        api_namespace=raw.get("api_namespace", "wc/v3"),
        consumer_key=raw["consumer_key"],
        consumer_secret=raw["consumer_secret"],
        permissions=raw.get("permissions", "read"),
    )


def credential_path_for_env() -> Path:
    """Allow override via HERMES_WANNAVEG_CRED env var (used in CI / tests)."""
    override = os.environ.get("HERMES_WANNAVEG_CRED")
    return Path(override) if override else DEFAULT_CREDENTIAL_PATH
