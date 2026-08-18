"""PostgreSQL advisory locks.

Several things in LumaIndex must not run twice at once across gunicorn workers
and the sync worker — cache eviction, and syncing one Drive connection. A
database advisory lock gives mutual exclusion without adding Redis, which PRD
§4 and §36 ask us to defer.

Session-scoped rather than transaction-scoped: these guard long operations
(a Drive walk, a download) that should not be wrapped in one transaction.

Note that PostgreSQL advisory locks are re-entrant *within a session*. The
mutual exclusion is between database connections — which is what we want, since
the contenders are separate processes (gunicorn workers and the sync worker) —
but two calls on the same connection will both succeed.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager

from django.db import connection

logger = logging.getLogger("lumaindex.db")


def _lock_id(key: str) -> int:
    """Map a name to the signed 64-bit integer pg_advisory_lock wants."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)


@contextmanager
def advisory_lock(key: str, *, blocking: bool = True):
    """Hold a named lock. Yields True if acquired, False if it was already held.

    With blocking=False the caller must check the yielded value — that is the
    whole point for a worker deciding whether someone else already has this
    connection in flight.
    """
    lock_id = _lock_id(key)
    acquired = False
    try:
        with connection.cursor() as cursor:
            if blocking:
                cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
                acquired = True
            else:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
                acquired = bool(cursor.fetchone()[0])
        yield acquired
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
            except Exception:
                # The lock is released when the session ends regardless; failing
                # to unlock must not mask whatever the caller was doing.
                logger.warning("could not release advisory lock",
                               extra={"event": "db.advisory_unlock_failed", "key": key})
