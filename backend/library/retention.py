"""When the trash empties itself.

This is the one place in the application that destroys a file nobody asked it
to destroy, which is why it is off unless somebody turns it on. Storage here is
canonical (see `storage.py`): an uploaded PDF may be the only copy its owner
has, and the deletion path is deliberately two explicit steps. A sweep that
quietly made the second step for them would undo that.

Turned on, it earns its keep: trashed books still occupy the disk and still
count towards a quota, so a trash nobody empties is a quota nobody can recover.

The invariant it leans on is that `Folder.trash()` stamps a whole subtree with
one timestamp, so an expired folder's contents expired at the same moment. That
is checked rather than assumed — a cascade delete does not ask whether the rows
beneath it were trashed, and the cost of being wrong is somebody's only copy.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Book, Folder
from .storage import LibraryStorage

logger = logging.getLogger("lumaindex.retention")

# A sweep does this much and stops, so one enormous trash cannot hold the
# worker for minutes on end. Whatever is left goes on the next pass.
SWEEP_LIMIT = 200


def retention_days() -> int:
    """How long trashed items are kept. 0 means for ever."""
    return max(0, int(getattr(settings, "TRASH_RETENTION_DAYS", 0)))


def cutoff(now=None):
    """Anything trashed before this is due for deletion, or None if never."""
    days = retention_days()
    if not days:
        return None
    return (now or timezone.now()) - timedelta(days=days)


def expires_at(deleted_at):
    """When a given trashed item will be destroyed, or None if never."""
    days = retention_days()
    if not days or deleted_at is None:
        return None
    return deleted_at + timedelta(days=days)


def purge_expired(*, now=None, limit: int = SWEEP_LIMIT) -> dict[str, int]:
    """Destroy trashed items past their retention, oldest first.

    Books before folders, so a folder is only ever deleted once the books it
    held have been accounted for and their blobs released.
    """
    due = cutoff(now)
    if due is None:
        return {"folders": 0, "books": 0, "files": 0, "skipped": 0}

    storage = LibraryStorage()
    keys: list[str] = []
    folders = books = skipped = 0

    expired_books = list(
        Book.objects.filter(deleted_at__isnull=False, deleted_at__lt=due)
        .select_related("source")
        .order_by("deleted_at", "pk")[:limit]
    )
    for book in expired_books:
        key = getattr(book.source, "storage_key", None)
        with transaction.atomic():
            book.delete()
        if key:
            keys.append(key)
        books += 1

    remaining = max(0, limit - books)
    if remaining:
        for folder in _expired_top_level_folders(due, remaining):
            removed, folder_keys, refused = _purge_folder(folder)
            if refused:
                skipped += 1
                continue
            folders += removed["folders"]
            books += removed["books"]
            keys.extend(folder_keys)

    # Blobs last, and only once no row points at them: two books can share one
    # file, and the other may not be trashed at all.
    files = sum(1 for key in dict.fromkeys(keys) if storage.delete_if_unreferenced(key))

    result = {"folders": folders, "books": books, "files": files, "skipped": skipped}
    if any(result.values()):
        logger.info("trash swept", extra={"event": "library.retention.swept", **result})
    return result


def _expired_top_level_folders(due, limit: int) -> list[Folder]:
    """Expired folders whose parent is not itself expired.

    Deleting a parent takes its children with it, so starting anywhere else
    means walking rows that are about to disappear underneath us.
    """
    expired = Folder.objects.filter(deleted_at__isnull=False, deleted_at__lt=due)
    expired_ids = set(expired.values_list("pk", flat=True))
    return [f for f in expired.order_by("deleted_at", "pk")
            if f.parent_id not in expired_ids][:limit]


def _purge_folder(folder: Folder) -> tuple[dict[str, int], list[str], bool]:
    """Delete a folder and its subtree, unless something in it is still live.

    The refusal is the point. `Folder.trash()` cannot leave a live row beneath a
    trashed one and nothing can be moved into the trash afterwards, so this
    should never fire — but a cascade delete does not check, and the failure
    mode is silent destruction of a book somebody still had.
    """
    ids = [folder.pk, *folder.descendant_ids()]

    live_folders = Folder.objects.filter(pk__in=ids, deleted_at__isnull=True).count()
    live_books = Book.objects.filter(folder_id__in=ids, deleted_at__isnull=True).count()
    if live_folders or live_books:
        logger.warning(
            "refused to sweep a folder holding live items",
            extra={"event": "library.retention.refused", "folder_id": folder.pk,
                   "live_folders": live_folders, "live_books": live_books},
        )
        return {"folders": 0, "books": 0}, [], True

    doomed = Book.objects.filter(folder_id__in=ids)
    keys = [key for key in doomed.values_list("source__storage_key", flat=True) if key]
    book_count = doomed.count()

    with transaction.atomic():
        Folder.objects.filter(pk__in=ids).delete()   # cascades to books and sources

    return {"folders": len(ids), "books": book_count}, keys, False
