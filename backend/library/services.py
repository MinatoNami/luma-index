"""Ingesting uploads into the library."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .documents import DocumentError, probe, render_thumbnail
from .models import Book, BookSource, Folder, UploadBatch
from .storage import LibraryStorage, StorageError
from .zip_import import ZipImportError, extract_entry, scan

logger = logging.getLogger("lumaindex.ingest")

PDF_MAGIC = b"%PDF-"
DOCUMENT_BATCH = 25
MAX_ERROR_SUMMARY = 4000


class IngestError(Exception):
    pass


def title_from(filename: str) -> str:
    return (Path(filename).stem.strip() or filename)[:512]


def ensure_folder_path(owner, parts: tuple[str, ...], *,
                       parent: Folder | None = None) -> Folder | None:
    """Create (or find) a chain of folders, returning the innermost.

    Reuses a live folder of the same name rather than making a second one, so
    re-importing an archive lands the files back where they were instead of
    building `Programming (2)`.
    """
    current = parent
    for name in parts:
        current, _ = Folder.objects.get_or_create(
            owner=owner, parent=current, name=name[:255], deleted_at=None,
            defaults={},
        )
    return current


def find_duplicate(owner, folder: Folder | None, storage_key: str) -> Book | None:
    """A live book in the same folder with byte-identical contents."""
    return Book.objects.live().filter(
        owner=owner, folder=folder, source__storage_key=storage_key
    ).first()


@transaction.atomic
def create_book(owner, *, folder: Folder | None, storage_key: str, filename: str,
                size: int, content_type: str = "application/pdf") -> Book:
    book = Book.objects.create(owner=owner, folder=folder, title=title_from(filename))
    BookSource.objects.create(
        book=book, storage_key=storage_key, original_filename=filename[:512],
        content_type=content_type, file_size=size,
    )
    return book


def store_upload(owner, upload, *, folder: Folder | None = None,
                 storage: LibraryStorage | None = None) -> tuple[Book | None, str]:
    """Store one uploaded PDF.

    Returns (book, outcome) where outcome is 'imported' or 'duplicate'.
    The file is sniffed rather than trusted: a browser-supplied content type
    says nothing about what is actually in the bytes.
    """
    storage = storage or LibraryStorage()

    head = upload.read(len(PDF_MAGIC))
    upload.seek(0)
    if not head.startswith(PDF_MAGIC):
        raise IngestError("That file is not a PDF.")

    max_bytes = int(getattr(settings, "MAX_UPLOAD_BYTES", 0))
    if max_bytes and upload.size > max_bytes:
        raise IngestError(
            f"That file is {upload.size // 1024**2} MiB; the limit is {max_bytes // 1024**2} MiB."
        )

    blob = storage.store_stream(upload.chunks(), expected_size=upload.size)

    if existing := find_duplicate(owner, folder, blob.storage_key):
        logger.info("skipped duplicate upload",
                    extra={"event": "ingest.duplicate", "book_id": existing.pk})
        return existing, "duplicate"

    book = create_book(owner, folder=folder, storage_key=blob.storage_key,
                       filename=upload.name or "upload.pdf", size=blob.size,
                       content_type=getattr(upload, "content_type", "") or "application/pdf")
    logger.info("stored upload", extra={"event": "ingest.stored", "book_id": book.pk})
    return book, "imported"


# --------------------------------------------------------------------------- #
# ZIP batches
# --------------------------------------------------------------------------- #

def process_zip_batch(batch: UploadBatch, *, storage: LibraryStorage | None = None) -> UploadBatch:
    """Extract an uploaded archive into the library.

    Per-entry failures are counted and the import continues: one corrupt PDF in
    a folder of four hundred should not cost the other 399.
    """
    storage = storage or LibraryStorage()
    batch.status = UploadBatch.Status.RUNNING
    batch.started_at = timezone.now()
    batch.save(update_fields=["status", "started_at"])

    archive = Path(batch.staged_path)
    errors: list[str] = []

    try:
        # `Path("")` is `Path(".")`, which exists — so an empty staged_path would
        # otherwise reach zipfile and surface as "Is a directory: '.'".
        if not batch.staged_path or not archive.is_file():
            raise ZipImportError("The uploaded archive is no longer on disk.")
        result = scan(archive)
    except (ZipImportError, OSError) as exc:
        batch.status = UploadBatch.Status.FAILED
        batch.error_summary = str(exc)[:MAX_ERROR_SUMMARY]
        batch.finished_at = timezone.now()
        batch.save()
        _discard_staged(batch)
        return batch

    batch.discovered = len(result.entries)
    batch.skipped_unsupported = result.skipped_unsupported
    errors.extend(result.rejected)
    batch.save(update_fields=["discovered", "skipped_unsupported"])

    staging = Path(settings.UPLOAD_STAGING_DIR) / f"batch-{batch.pk}"
    staging.mkdir(parents=True, exist_ok=True)

    for entry in result.entries:
        temporary = staging / "entry.pdf"
        try:
            extract_entry(archive, entry, temporary)
            blob = storage.store_file(temporary)

            folder = ensure_folder_path(batch.owner, entry.folder_parts,
                                        parent=batch.target_folder)
            if find_duplicate(batch.owner, folder, blob.storage_key):
                batch.skipped_duplicate += 1
            else:
                create_book(batch.owner, folder=folder, storage_key=blob.storage_key,
                            filename=entry.name, size=blob.size)
                batch.imported += 1
        except (ZipImportError, StorageError, OSError) as exc:
            batch.failed += 1
            errors.append(f"{entry.display_path}: {exc}")
            logger.warning("zip entry failed",
                           extra={"event": "ingest.zip.entry_failed",
                                  "batch_id": batch.pk, "reason": type(exc).__name__})
        finally:
            temporary.unlink(missing_ok=True)

    try:
        staging.rmdir()
    except OSError:
        pass

    batch.error_summary = "\n".join(errors)[:MAX_ERROR_SUMMARY]
    batch.status = (UploadBatch.Status.OK if not batch.failed and not errors
                    else UploadBatch.Status.PARTIAL)
    batch.finished_at = timezone.now()
    batch.save()
    _discard_staged(batch)

    logger.info("zip import finished",
                extra={"event": "ingest.zip.done", "batch_id": batch.pk,
                       "status": batch.status, **batch.counts})
    return batch


def _discard_staged(batch: UploadBatch) -> None:
    """Remove the uploaded archive once it has been read.

    The books are stored by now; keeping the ZIP would silently double the disk
    every import costs.
    """
    if not batch.staged_path:
        return
    try:
        Path(batch.staged_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove staged upload",
                       extra={"event": "ingest.staging.orphan", "batch_id": batch.pk})
    batch.staged_path = ""
    batch.save(update_fields=["staged_path"])


# --------------------------------------------------------------------------- #
# Probing and thumbnails
# --------------------------------------------------------------------------- #

def pending_documents():
    """Books whose contents have not been examined yet."""
    from django.db.models import Q

    return BookSource.objects.filter(
        availability_status=BookSource.Availability.AVAILABLE,
        book__deleted_at__isnull=True,
    ).filter(
        Q(book__page_count__isnull=True) | Q(book__thumbnail_path="")
    ).select_related("book").order_by("pk")


def process_pending_documents(*, limit: int = DOCUMENT_BATCH,
                              storage: LibraryStorage | None = None) -> dict[str, int]:
    """Probe page count and text layer, and render a thumbnail, for a batch.

    Done outside the request so an upload returns as soon as the bytes are
    safe. The book appears immediately; its cover and page count follow.
    """
    sources = list(pending_documents()[:limit])
    if not sources:
        return {"processed": 0, "failed": 0, "remaining": 0}

    storage = storage or LibraryStorage()
    processed = failed = 0

    for source in sources:
        path = storage.path_for(source.storage_key)
        try:
            if not path.exists():
                # The row says the file is there and it is not. Flag it rather
                # than deleting the book: the metadata and any annotations are
                # still worth more than a tidy database.
                BookSource.objects.filter(pk=source.pk).update(
                    availability_status=BookSource.Availability.MISSING
                )
                failed += 1
                continue

            info = probe(path)
            thumbnail = (Path(settings.THUMBNAIL_DIR) / source.storage_key[:2]
                         / f"{source.storage_key}.webp")
            render_thumbnail(path, thumbnail)

            Book.objects.filter(pk=source.book_id).update(
                page_count=info.page_count,
                has_text_layer=info.has_text_layer,
                thumbnail_path=str(thumbnail.relative_to(settings.THUMBNAIL_DIR)),
            )
            processed += 1
        except (DocumentError, OSError) as exc:
            failed += 1
            BookSource.objects.filter(pk=source.pk).update(
                availability_status=BookSource.Availability.ERROR
            )
            logger.warning("document processing failed",
                           extra={"event": "ingest.document.failed", "source_id": source.pk,
                                  "reason": type(exc).__name__})

    return {"processed": processed, "failed": failed, "remaining": pending_documents().count()}
