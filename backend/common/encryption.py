"""Symmetric encryption for provider credentials stored in PostgreSQL.

Used by `integrations.google_drive` (Phase 2) for OAuth refresh tokens, which
PRD §9 requires to be encrypted at rest, never logged, and never returned to
another user.

Key management, stated plainly so it is not discovered during an incident:

* `LUMA_FIELD_ENCRYPTION_KEY` encrypts and decrypts.
* `LUMA_FIELD_ENCRYPTION_KEYS_LEGACY` only decrypts, so a key can be rotated
  without a flag day: prepend the old key there, deploy the new primary, run
  `manage.py rotate_encrypted_fields`, then drop the legacy entry.
* Losing every key makes stored tokens unrecoverable — users must reconnect
  Drive. The key therefore has to be backed up somewhere other than the
  database dump it protects.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@lru_cache(maxsize=1)
def _cipher() -> MultiFernet:
    primary = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not primary:
        raise ImproperlyConfigured(
            "LUMA_FIELD_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )
    keys = [primary, *getattr(settings, "FIELD_ENCRYPTION_KEYS_LEGACY", [])]
    try:
        return MultiFernet([Fernet(key.encode() if isinstance(key, str) else key)
                            for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(f"Invalid field encryption key: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _cipher().decrypt(ciphertext.encode()).decode()


class EncryptedTextField(models.TextField):
    """Transparently encrypted text.

    The value is unreadable in the database, in `dumpdata`, and in Django Admin
    unless a view deliberately decrypts it. Note the tradeoff: the ciphertext is
    not searchable or indexable, which is fine for credentials and wrong for
    anything you need to query.
    """

    def get_prep_value(self, value):  # type: ignore[override]
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return decrypt(value)
        except InvalidToken:
            # A wrong or rotated-away key. Surfacing None lets the caller mark
            # the connection as needing re-authorization instead of crashing
            # every request that touches the row.
            return None
