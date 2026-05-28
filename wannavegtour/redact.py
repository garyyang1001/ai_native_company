"""Small PII redaction helpers for OP assistant event logging.

This module is a first-iteration helper for the OP bot. It is NOT a full
company-wide PII policy — see docs/plans/2026-05-28-learning-loop-design-v0.2.md
Q2 lock.
"""

from __future__ import annotations

import hashlib
import re

_HASH_LEN = 16
_PREVIEW_LEN = 240

_LINE_USER_RE = re.compile(r"\bU[0-9a-fA-F]{32}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
    r"|(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_LEN]


def hash_message(text: str) -> str:
    """sha256 of full original text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_user_id(uid: str) -> str:
    """Stable hash for LINE user_id."""
    return f"user:{_short_hash(uid)}"


def _replace(pattern: re.Pattern[str], kind: str, text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"[{kind}:{_short_hash(match.group(0))}]"

    return pattern.sub(repl, text)


def redact_text(text: str) -> tuple[str, str]:
    """Return (redacted_preview, message_hash).

    Preview strips/hashes phone numbers, LINE user IDs, and common emails.
    """
    message_hash = hash_message(text)
    redacted = _replace(_LINE_USER_RE, "line_user", text)
    redacted = _replace(_EMAIL_RE, "email", redacted)
    redacted = _replace(_PHONE_RE, "phone", redacted)
    return redacted[:_PREVIEW_LEN], message_hash
