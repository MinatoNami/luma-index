"""Server-side PDF cache.

PRD §25: Drive stays canonical storage; Django keeps a local copy so reads do
not hit the Drive API every time, and — the part that matters for §18 — so a
shared reader can be served without any access to the owner's Drive.

The rules this file implements:

* keyed on stable provider identity plus a content version, never a filename
* a changed file invalidates itself rather than serving stale bytes
* a maximum size that is *enforced*, with least-recently-used eviction
* eviction serialised across processes, so workers cannot race each other

The rule it deliberately does not implement is authorization. Nothing here
checks who is asking; that is the view's job on every request, cache hit
included. A cache that decides access is a cache that leaks (PRD §29).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from common.db import advisory_lock

logger = logging.getLogger("lumaindex.cache")

CACHE_KEY_RE = re.compile(r"^[0-9a-f]{16,128}$")
EVICTION_LOCK = "lumaindex.pdf_cache.eviction"

# Evict down to this share of the cap, so a cache sitting exactly at the limit
# does not trigger a sweep on every single write.
EVICTION_TARGET = 0.9


class CacheError(Exception):
    pass


@dataclass(frozen=True)
class EvictionResult:
    scanned: int = 0
    removed: int = 0
    bytes_freed: int = 0
    skipped: bool = False  # another process held the lock


class PdfCache:
    def __init__(self, root: Path | None = None, max_bytes: int | None = None):
        self.root = Path(root or settings.PDF_CACHE_DIR)
        self.max_bytes = int(max_bytes if max_bytes is not None else settings.PDF_CACHE_MAX_BYTES)

    # -- paths -------------------------------------------------------------- #

    def path_for(self, cache_key: str) -> Path:
        """Where a key lives on disk.

        Keys are hex digests, so the pattern check is belt and braces — but it
        is the difference between a bug and a path traversal if a future caller
        ever passes something provider-supplied.
        """
        if not CACHE_KEY_RE.match(cache_key):
            raise CacheError(f"Refusing to use a non-hex cache key: {cache_key!r}")
        # Shard by prefix: one directory with 50k entries is slow to list and
        # unpleasant to inspect.
        return self.root / cache_key[:2] / cache_key[2:4] / f"{cache_key}.pdf"

    # -- reads -------------------------------------------------------------- #

    def get(self, cache_key: str) -> Path | None:
        """The cached file, or None. Marks it as recently used."""
        path = self.path_for(cache_key)
        if not path.exists():
            return None
        try:
            # Explicit, because most filesystems mount with relatime and would
            # not otherwise record this read — which would make LRU meaningless.
            os.utime(path, None)
        except OSError:
            pass
        return path

    def contains(self, cache_key: str) -> bool:
        return self.path_for(cache_key).exists()

    # -- writes ------------------------------------------------------------- #

    def store(self, cache_key: str, writer) -> Path:
        """Populate a key. `writer(handle)` writes the bytes.

        Writes to a temporary file in the same directory and renames it into
        place, so a reader never observes a partial file and an interrupted
        download leaves nothing behind.
        """
        path = self.path_for(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)

        handle, staging = tempfile.mkstemp(dir=path.parent, suffix=".part")
        staging_path = Path(staging)
        try:
            with os.fdopen(handle, "wb") as destination:
                writer(destination)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(staging_path, path)
        except BaseException:
            staging_path.unlink(missing_ok=True)
            raise

        logger.info("cached pdf", extra={"event": "cache.store", "cache_key": cache_key,
                                         "bytes": path.stat().st_size})
        return path

    def fetch(self, cache_key: str, writer) -> Path:
        """Return the cached file, populating it once if absent.

        The advisory lock means two readers opening the same uncached book
        download it once, not twice — which on a large book is the difference
        between one Drive read and several.
        """
        existing = self.get(cache_key)
        if existing is not None:
            return existing

        with advisory_lock(f"lumaindex.pdf_cache.fetch:{cache_key}"):
            # Whoever held the lock may have just finished the download.
            existing = self.get(cache_key)
            if existing is not None:
                return existing
            path = self.store(cache_key, writer)

        self.evict_if_needed()
        return path

    def forget(self, cache_key: str) -> bool:
        path = self.path_for(cache_key)
        if path.exists():
            path.unlink()
            return True
        return False

    # -- size and eviction --------------------------------------------------- #

    def entries(self) -> list[tuple[Path, os.stat_result]]:
        if not self.root.exists():
            return []
        found = []
        for path in self.root.rglob("*.pdf"):
            try:
                found.append((path, path.stat()))
            except OSError:
                continue
        return found

    def total_bytes(self) -> int:
        return sum(stat.st_size for _, stat in self.entries())

    def evict_if_needed(self) -> EvictionResult:
        if self.max_bytes <= 0:
            return EvictionResult()
        if self.total_bytes() <= self.max_bytes:
            return EvictionResult()
        return self.evict_to_limit()

    def evict_to_limit(self) -> EvictionResult:
        """Delete least-recently-used files until the cache fits.

        Serialised with an advisory lock. Without it, concurrent sweeps each
        compute a total that ignores the other's deletions and evict far more
        than intended.

        Deleting a file another process is streaming is safe on Linux: the
        reader holds an open descriptor and keeps reading the unlinked inode
        until it closes. The bytes are only reclaimed afterwards.
        """
        with advisory_lock(EVICTION_LOCK, blocking=False) as acquired:
            if not acquired:
                logger.info("eviction already running elsewhere",
                            extra={"event": "cache.evict.skipped"})
                return EvictionResult(skipped=True)

            entries = self.entries()
            total = sum(stat.st_size for _, stat in entries)
            if total <= self.max_bytes:
                return EvictionResult(scanned=len(entries))

            target = int(self.max_bytes * EVICTION_TARGET)
            entries.sort(key=lambda item: item[1].st_mtime)  # oldest use first

            removed = freed = 0
            for path, stat in entries:
                if total <= target:
                    break
                try:
                    path.unlink()
                except OSError:
                    continue
                total -= stat.st_size
                freed += stat.st_size
                removed += 1

            logger.info("cache eviction complete",
                        extra={"event": "cache.evict", "removed": removed,
                               "bytes_freed": freed, "remaining_bytes": total})
            return EvictionResult(scanned=len(entries), removed=removed, bytes_freed=freed)

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
