"""Receiving one large file in pieces.

A single multipart POST is all-or-nothing. On a link that drops once every few
minutes — a Tailscale DERP relay, hotel wifi, a phone — a 600 MB upload never
lands, and every attempt starts again from zero. Worse, there is nothing to
distinguish a slow upload from a stuck one until it fails.

So a large file is sent as a sequence of chunks appended to one staging file,
and `ChunkedUpload.received` records how much is actually on disk. That number,
not anything the client claims, decides where the next chunk goes:

* a chunk that arrives twice has an offset behind `received` and is dropped
* a chunk that arrives out of order is refused, with `received` in the reply so
  the client can resync rather than guess
* a write that would run past the declared size is truncated to it

Completion hands the assembled file to `store_upload`, so a chunked upload goes
through exactly the same magic-byte check, size limit, quota accounting and
deduplication as a small one. There is no second path to keep in step.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .models import ChunkedUpload, Folder
from .quota import ensure_room
from .services import IngestError, store_upload
from .storage import LibraryStorage

logger = logging.getLogger("lumaindex.ingest.chunked")

# What the client is told to send. Small enough that losing one to a dropped
# connection is cheap, large enough that a 2 GiB file is not 2000 requests.
CHUNK_SIZE = 8 * 1024 * 1024

# An upload nobody has touched for this long is abandoned, and its staging file
# is holding disk nothing will ever claim.
STALE_AFTER_HOURS = 24

WRITE_BLOCK = 1024 * 256


class ChunkConflict(Exception):
    """The chunk did not start where the file currently ends."""

    def __init__(self, received: int):
        super().__init__(f"Expected the next chunk at byte {received}.")
        self.received = received


def staging_dir() -> Path:
    return Path(settings.UPLOAD_STAGING_DIR) / "chunked"


def begin(owner, *, filename: str, size: int, folder: Folder | None = None) -> ChunkedUpload:
    """Reserve a staging file, after the checks that would refuse it anyway.

    Refusing here costs the user nothing; refusing at the end costs them the
    whole upload.
    """
    if size <= 0:
        raise IngestError("That file is empty.")

    max_bytes = int(getattr(settings, "MAX_UPLOAD_BYTES", 0))
    if max_bytes and size > max_bytes:
        raise IngestError(
            f"That file is {size // 1024**2} MiB; the limit is {max_bytes // 1024**2} MiB."
        )

    LibraryStorage().check_space_for(size)
    ensure_room(owner)

    upload = ChunkedUpload.objects.create(
        owner=owner, original_filename=(filename or "upload.pdf")[:512],
        declared_size=size, target_folder=folder,
    )

    directory = staging_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"upload-{upload.pk}.part"
    path.touch()
    upload.staged_path = str(path)
    upload.save(update_fields=["staged_path", "updated_at"])

    logger.info("chunked upload started",
                extra={"event": "ingest.chunked.begin", "upload_id": upload.pk,
                       "bytes": size})
    return upload


def append(upload: ChunkedUpload, *, offset: int, stream) -> int:
    """Append one chunk and return the new `received`.

    A repeat of the chunk already written is a no-op rather than an error: a
    client that lost the response but not the connection would otherwise be
    stuck retrying something that already worked.
    """
    path = Path(upload.staged_path)
    if not path.exists():
        raise IngestError("This upload is no longer staged. Start it again.")

    if offset != upload.received:
        # Behind means a duplicate, ahead means a hole. Neither can be appended,
        # and both are fixed the same way: tell the client where we actually are.
        raise ChunkConflict(upload.received)

    remaining = upload.declared_size - upload.received
    if remaining <= 0:
        return upload.received

    written = 0
    with path.open("ab") as out:
        for block in iter(lambda: stream.read(WRITE_BLOCK), b""):
            if not block:
                break
            # Never past the declared size: the length is what the disk and
            # quota checks were made against.
            allowed = min(len(block), remaining - written)
            if allowed <= 0:
                break
            out.write(block[:allowed])
            written += allowed
        out.flush()

    # Read back rather than trusting the counter, so a partial write leaves the
    # client resuming from where the bytes really end.
    upload.received = path.stat().st_size
    upload.save(update_fields=["received", "updated_at"])
    return upload.received


def finish(upload: ChunkedUpload, *, storage: LibraryStorage | None = None):
    """Hand the assembled file to the ordinary upload path."""
    path = Path(upload.staged_path)
    if not path.exists():
        raise IngestError("This upload is no longer staged. Start it again.")

    actual = path.stat().st_size
    if actual < upload.declared_size:
        raise ChunkConflict(actual)

    storage = storage or LibraryStorage()
    try:
        with path.open("rb") as handle:
            # A Django File so store_upload sees what it sees for any other
            # upload: .size, .chunks(), .read(), .seek(), .name.
            wrapped = File(handle, name=upload.original_filename)
            book, outcome = store_upload(upload.owner, wrapped,
                                         folder=upload.target_folder, storage=storage)
    finally:
        path.unlink(missing_ok=True)
        upload.delete()

    logger.info("chunked upload finished",
                extra={"event": "ingest.chunked.finish", "outcome": outcome,
                       "book_id": getattr(book, "pk", None)})
    return book, outcome


def abandon(upload: ChunkedUpload) -> None:
    Path(upload.staged_path).unlink(missing_ok=True)
    upload.delete()


def purge_stale(*, hours: int = STALE_AFTER_HOURS, now=None) -> int:
    """Drop uploads nobody has added to for a while.

    Their staging files are holding disk that nothing will ever claim, and the
    disk check that let them start assumed they would finish.
    """
    cutoff = (now or timezone.now()) - timedelta(hours=hours)
    stale = list(ChunkedUpload.objects.filter(updated_at__lt=cutoff))
    for upload in stale:
        with transaction.atomic():
            abandon(upload)
    if stale:
        logger.info("abandoned chunked uploads removed",
                    extra={"event": "ingest.chunked.purged", "count": len(stale)})
    return len(stale)
