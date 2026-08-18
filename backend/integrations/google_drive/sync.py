"""Synchronising a Drive connection into the library.

The safety rule that shapes this file: **a short listing is not a deletion.**
Drive can return fewer files because a folder became unreadable, a quota was
hit, or the API had a bad minute. If any of that happens, nothing is marked
missing — PRD §13 and §26 require that a temporarily unavailable file never
costs a user their reading state, and the only way to honour that is to refuse
to draw conclusions from an incomplete walk.

Work is split in two so a large first import does not stall:

1. `sync_connection` — metadata only. Fast, no downloads, always completes.
2. `process_pending_documents` — downloads a bounded number of files per run to
   probe page count, detect a text layer, and render a thumbnail.

The worker loops, so a 2,000-book library fills in over successive passes
instead of one enormous run that fails halfway and starts over.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.db import advisory_lock
from library.cache import PdfCache
from library.documents import DocumentError, probe, render_thumbnail
from library.models import Book, BookSource

from . import oauth
from .client import DriveClient, DriveFile, WalkStats
from .errors import DriveAuthError, DriveError
from .models import DriveConnection, SyncRun

logger = logging.getLogger("lumaindex.drive.sync")

# Documents downloaded and probed per run. Keeps one pass bounded; the worker
# comes straight back for the next batch.
DOCUMENT_BATCH = 25
MAX_ERROR_SUMMARY = 4000


def connection_lock_key(connection_id: int) -> str:
    return f"lumaindex.drive.sync:{connection_id}"


@dataclass
class _Tally:
    discovered: int = 0
    added: int = 0
    updated: int = 0
    marked_missing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    complete: bool = True

    def note(self, message: str) -> None:
        self.errors.append(message)
        self.complete = False


def _title_from(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return (stem or filename)[:512]


def _apply(source: BookSource, file: DriveFile) -> bool:
    """Copy provider metadata onto a source. Returns True if anything changed."""
    fields = {
        "provider_parent_id": file.parent_id,
        "original_path": file.path[:2048],
        "filename": file.name[:512],
        "mime_type": file.mime_type,
        "file_size": file.size,
        "provider_modified_at": file.modified_at,
        "provider_checksum": file.checksum,
        "availability_status": BookSource.Availability.AVAILABLE,
        "last_seen_at": timezone.now(),
    }
    changed = [name for name, value in fields.items()
               if name != "last_seen_at" and getattr(source, name) != value]
    for name, value in fields.items():
        setattr(source, name, value)
    source.save()
    return bool(changed)


@transaction.atomic
def _upsert(connection: DriveConnection, file: DriveFile, tally: _Tally) -> None:
    source = BookSource.objects.select_for_update().filter(
        provider=BookSource.Provider.GOOGLE_DRIVE, provider_file_id=file.id
    ).first()

    if source is None:
        book = Book.objects.create(owner=connection.user, title=_title_from(file.name))
        source = BookSource(book=book, drive_connection=connection,
                            provider_file_id=file.id, filename=file.name[:512])
        _apply(source, file)
        tally.added += 1
        return

    # Re-point a source whose connection was cleared by a previous disconnect,
    # so reconnecting adopts the existing books rather than duplicating them.
    if source.drive_connection_id != connection.pk:
        source.drive_connection = connection

    content_changed = (
        source.provider_checksum != file.checksum
        or source.provider_modified_at != file.modified_at
    )
    if _apply(source, file):
        tally.updated += 1

    if content_changed:
        # The bytes differ, so the cached copy and everything derived from it
        # are stale. Reading state and annotations are untouched — they belong
        # to the Book, not to this revision of the file.
        Book.objects.filter(pk=source.book_id).update(
            page_count=None, has_text_layer=None, thumbnail_path=""
        )


def sync_connection(connection: DriveConnection, *, client: DriveClient | None = None) -> SyncRun:
    """Walk every enabled root and reconcile the library. Metadata only."""
    with advisory_lock(connection_lock_key(connection.pk), blocking=False) as acquired:
        if not acquired:
            logger.info("sync already running for this connection",
                        extra={"event": "drive.sync.busy", "connection_id": connection.pk})
            raise SyncBusy(f"A sync is already running for connection {connection.pk}.")
        return _sync(connection, client)


class SyncBusy(RuntimeError):
    """Another process holds this connection's sync lock."""


def _sync(connection: DriveConnection, client: DriveClient | None) -> SyncRun:
    run = SyncRun.objects.create(drive_connection=connection)
    tally = _Tally()

    try:
        if client is None:
            client = DriveClient(oauth.get_access_token(connection))
    except DriveAuthError as exc:
        # Expected weekly under Testing mode. Record and stop; nothing is
        # marked missing, because we learned nothing about the files.
        run.status = SyncRun.Status.FAILED
        run.error_summary = f"Authorization lost: {exc}"
        run.finished_at = timezone.now()
        run.save()
        return run
    except DriveError as exc:
        run.status = SyncRun.Status.FAILED
        run.error_summary = f"Drive unavailable: {exc}"
        run.finished_at = timezone.now()
        run.save()
        return run

    seen: set[str] = set()

    for root in connection.roots.filter(sync_enabled=True):
        stats = WalkStats()
        try:
            for file in client.walk_pdfs(root.provider_folder_id, root_name=root.name,
                                         stats=stats):
                tally.discovered += 1
                seen.add(file.id)
                try:
                    _upsert(connection, file, tally)
                except Exception as exc:
                    tally.failed += 1
                    tally.note(f"{file.path}: {type(exc).__name__}: {exc}")
                    logger.warning("failed to record a drive file",
                                   extra={"event": "drive.sync.file_failed",
                                          "file_id": file.id})
        except DriveAuthError as exc:
            tally.note(f"authorization lost during {root.name}: {exc}")
            break
        except DriveError as exc:
            tally.note(f"{root.name}: {type(exc).__name__}: {exc}")
            continue

        # Skipped subfolders mean the walk under-reports. Recording that is what
        # stops the missing-file pass below from acting on bad information.
        for message in stats.errors:
            tally.note(message)

        if not stats.errors:
            root.last_synced_at = timezone.now()
            root.save(update_fields=["last_synced_at", "updated_at"])

    if tally.complete:
        tally.marked_missing = _mark_missing(connection, seen)
    elif seen:
        logger.info("skipping missing-file detection after an incomplete walk",
                    extra={"event": "drive.sync.partial", "connection_id": connection.pk,
                           "seen": len(seen)})

    try:
        if not connection.start_page_token:
            connection.start_page_token = client.get_start_page_token()
    except DriveError:
        pass  # a nice-to-have for later incremental sync, never a sync failure

    run.discovered = tally.discovered
    run.added = tally.added
    run.updated = tally.updated
    run.marked_missing = tally.marked_missing
    run.failed = tally.failed
    run.error_summary = "\n".join(tally.errors)[:MAX_ERROR_SUMMARY]
    run.status = SyncRun.Status.OK if tally.complete and not tally.failed \
        else SyncRun.Status.PARTIAL
    run.finished_at = timezone.now()
    run.save()

    connection.last_synced_at = timezone.now()
    connection.sync_requested_at = None
    connection.save(update_fields=["last_synced_at", "sync_requested_at",
                                   "start_page_token", "updated_at"])

    logger.info("drive sync finished",
                extra={"event": "drive.sync.done", "connection_id": connection.pk,
                       "status": run.status, **run.counts})
    return run


def _mark_missing(connection: DriveConnection, seen: set[str]) -> int:
    """Flag sources that a *complete* walk did not encounter.

    Only ever called when every root walked cleanly. The status is a flag, not
    a deletion: PRD §13 requires that a file disappearing from Drive leaves the
    book, its progress, and its annotations intact.
    """
    stale = BookSource.objects.filter(
        drive_connection=connection,
        availability_status=BookSource.Availability.AVAILABLE,
    ).exclude(provider_file_id__in=seen)

    count = stale.count()
    if count:
        stale.update(availability_status=BookSource.Availability.MISSING,
                     updated_at=timezone.now())
        logger.info("marked sources missing",
                    extra={"event": "drive.sync.missing", "count": count,
                           "connection_id": connection.pk})
    return count


# --------------------------------------------------------------------------- #
# Document processing
# --------------------------------------------------------------------------- #

def pending_documents(connection: DriveConnection):
    """Books whose content has not been probed yet."""
    from django.db.models import Q

    return BookSource.objects.filter(
        drive_connection=connection,
        availability_status=BookSource.Availability.AVAILABLE,
    ).filter(
        Q(book__page_count__isnull=True) | Q(book__thumbnail_path="")
    ).select_related("book").order_by("pk")


def process_pending_documents(connection: DriveConnection, *, limit: int = DOCUMENT_BATCH,
                              client: DriveClient | None = None,
                              cache: PdfCache | None = None) -> dict[str, int]:
    """Download, probe, and thumbnail up to `limit` books."""
    sources = list(pending_documents(connection)[:limit])
    if not sources:
        return {"processed": 0, "failed": 0, "remaining": 0}

    cache = cache or PdfCache()
    if client is None:
        client = DriveClient(oauth.get_access_token(connection))

    processed = failed = 0
    for source in sources:
        try:
            path = cache.fetch(source.cache_key,
                               lambda handle, s=source: client.download(s.provider_file_id, handle))
            info = probe(path)

            thumbnail = Path(settings.THUMBNAIL_DIR) / source.cache_key[:2] / \
                f"{source.cache_key}.webp"
            render_thumbnail(path, thumbnail)

            Book.objects.filter(pk=source.book_id).update(
                page_count=info.page_count,
                has_text_layer=info.has_text_layer,
                thumbnail_path=str(thumbnail.relative_to(settings.THUMBNAIL_DIR)),
            )
            processed += 1
        except DriveAuthError:
            # No point continuing; every remaining download fails the same way.
            raise
        except (DriveError, DocumentError, OSError) as exc:
            failed += 1
            # A corrupt or unreadable PDF marks its own source and lets the rest
            # of the batch through (PRD §35).
            BookSource.objects.filter(pk=source.pk).update(
                availability_status=BookSource.Availability.ERROR
            )
            logger.warning("document processing failed",
                           extra={"event": "drive.document.failed", "source_id": source.pk,
                                  "reason": type(exc).__name__})

    return {"processed": processed, "failed": failed,
            "remaining": pending_documents(connection).count()}
