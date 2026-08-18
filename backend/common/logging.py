"""Structured logging with credential redaction.

PRD §32 requires that credentials and OAuth tokens are never logged. Relying on
every call site to remember that is not a control; this filter is.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

# Substrings that mark a key as sensitive, and inline patterns that leak tokens
# into free-text messages (e.g. an exception repr containing a query string).
SENSITIVE_KEY_PARTS = (
    "password", "passwd", "secret", "token", "authorization", "auth",
    "api_key", "apikey", "credential", "cookie", "session", "refresh",
    "client_secret", "private_key", "encryption_key",
)

_INLINE_PATTERNS = (
    re.compile(r"(?i)\b(access_token|refresh_token|id_token|client_secret|password)"
               r"\s*[=:]\s*\"?[^\s\"&,}]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"),
    # Google OAuth refresh tokens.
    re.compile(r"\b1//[A-Za-z0-9._\-]{10,}"),
)

REDACTED = "[redacted]"


def _scrub_text(text: str) -> str:
    for pattern in _INLINE_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=" + REDACTED
                           if ("=" in m.group(0) or ":" in m.group(0)) else REDACTED, text)
    return text


def scrub(value: object, _depth: int = 0) -> object:
    """Recursively redact sensitive values from a structure bound for the log."""
    if _depth > 6:
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (REDACTED
                  if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
                  else scrub(item, _depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [scrub(item, _depth + 1) for item in value]
    if isinstance(value, str):
        return _scrub_text(value)
    return value


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = scrub(record.msg)
            if isinstance(record.args, dict):
                record.args = scrub(record.args)
            elif record.args:
                record.args = tuple(scrub(arg) for arg in record.args)
        except Exception:  # logging must never take the request down
            record.msg = REDACTED
            record.args = ()
        return True


# Attributes LogRecord always carries; anything else was passed via `extra`.
_STANDARD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class StructuredFormatter(logging.Formatter):
    """One JSON object per line — greppable, and ready for a log shipper later."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = scrub(value)
        if record.exc_info:
            payload["exception"] = _scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)
