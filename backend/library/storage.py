"""Content-addressed storage for uploaded PDFs.

This replaces the Drive-era PDF cache, and the difference matters: a cache can
be evicted because the bytes exist somewhere else, and this cannot. What is
here is the only copy the user has. So:

* nothing is ever deleted to reclaim space — an upload is refused instead
* a blob is removed only when no book references it any more
* writes are staged and renamed, so a failed upload leaves nothing behind

Files are addressed by the SHA-256 of their contents. Uploading the same PDF
twice therefore stores one copy, which makes retrying a half-finished ZIP
import free rather than doubling the disk it already used.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("lumaindex.storage")

STORAGE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
READ_CHUNK = 1024 * 256


class StorageError(Exception):
    pass


class InsufficientSpace(StorageError):
    """Refusing to write, because the disk is nearly full."""


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    path: Path
    size: int
    deduplicated: bool = False


class LibraryStorage:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.LIBRARY_DIR)

    # -- paths -------------------------------------------------------------- #

    def path_for(self, storage_key: str) -> Path:
        if not STORAGE_KEY_RE.match(storage_key):
            # The key is always a digest we computed. The check is what keeps
            # that true if a caller ever passes something user-supplied.
            raise StorageError(f"Refusing a non-digest storage key: {storage_key!r}")
        # Sharded: one directory holding 50k files is slow to list and painful
        # to inspect when something has gone wrong.
        return self.root / storage_key[:2] / storage_key[2:4] / f"{storage_key}.pdf"

    def exists(self, storage_key: str) -> bool:
        return self.path_for(storage_key).exists()

    def open(self, storage_key: str):
        return self.path_for(storage_key).open("rb")

    # -- space -------------------------------------------------------------- #

    def free_bytes(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.root)
        return usage.free

    def check_space_for(self, incoming_bytes: int) -> None:
        """Refuse before writing, not halfway through.

        Canonical storage cannot be evicted to recover, and a full disk also
        stops PostgreSQL accepting writes — so the whole instance goes down,
        not just uploads.
        """
        floor = int(getattr(settings, "MIN_FREE_DISK_BYTES", 0))
        free = self.free_bytes()
        if free - incoming_bytes < floor:
            raise InsufficientSpace(
                f"Not enough disk space: {free // 1024**2} MiB free, "
                f"need {(incoming_bytes + floor) // 1024**2} MiB."
            )

    def total_bytes(self) -> int:
        if not self.root.exists():
            return 0
        total = 0
        for path in self.root.rglob("*.pdf"):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    # -- writes -------------------------------------------------------------- #

    def store_stream(self, chunks, *, expected_size: int | None = None) -> StoredBlob:
        """Write an iterable of byte chunks, hashing as it goes.

        The digest is only known once everything has been read, so the data
        goes to a staging file first and is renamed into its final place after.
        That also means an interrupted upload leaves no half-file that a later
        read would mistake for a complete one.
        """
        if expected_size is not None:
            self.check_space_for(expected_size)

        self.root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        handle, staging = tempfile.mkstemp(dir=self.root, suffix=".part")
        staging_path = Path(staging)
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in chunks:
                    if not chunk:
                        continue
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())

            storage_key = digest.hexdigest()
            destination = self.path_for(storage_key)

            if destination.exists():
                # Identical bytes already stored. Drop the copy we just made.
                staging_path.unlink(missing_ok=True)
                return StoredBlob(storage_key, destination, destination.stat().st_size,
                                  deduplicated=True)

            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_path, destination)
            logger.info("stored file", extra={"event": "storage.store",
                                              "storage_key": storage_key, "bytes": size})
            return StoredBlob(storage_key, destination, size)
        except BaseException:
            staging_path.unlink(missing_ok=True)
            raise

    def store_file(self, source: Path) -> StoredBlob:
        with source.open("rb") as handle:
            return self.store_stream(iter(lambda: handle.read(READ_CHUNK), b""),
                                     expected_size=source.stat().st_size)

    # -- deletes -------------------------------------------------------------- #

    def delete_if_unreferenced(self, storage_key: str) -> bool:
        """Remove a blob only once nothing points at it.

        Content addressing means two books can share one file, so deleting a
        book must not assume it owns the bytes.
        """
        from .models import BookSource

        if BookSource.objects.filter(storage_key=storage_key).exists():
            return False

        path = self.path_for(storage_key)
        if not path.exists():
            return False
        path.unlink()
        logger.info("removed unreferenced file",
                    extra={"event": "storage.delete", "storage_key": storage_key})
        return True


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
