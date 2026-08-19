"""Doing one thing to a whole selection at once.

Looping the single-item endpoints from the browser would work, and it is what
this replaces. It costs one request per item, and — worse — it fails halfway
with no way to say what did and did not happen. Moving forty books into a
folder that already holds one of their names should not leave the user
guessing which thirty-nine arrived.

So every operation here is **partial by design**: an item that cannot be acted
on is skipped with a reason, and the rest still go through. That mirrors how a
ZIP import already treats one bad entry among four hundred, and it is what
makes the result worth showing to a person.

Ownership is filtered, never asserted. An id belonging to somebody else is
skipped exactly like an id that does not exist, because reporting the
difference would confirm the row is there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from .models import Book, CollectionBook, Folder, UserBookState


@dataclass
class BulkResult:
    """What happened, in the terms the person who asked would use."""

    folders: int = 0
    books: int = 0
    skipped: list[dict] = field(default_factory=list)

    def skip(self, kind: str, pk: int, reason: str) -> None:
        self.skipped.append({"kind": kind, "id": pk, "reason": reason})

    def as_dict(self) -> dict:
        return {"folders": self.folders, "books": self.books, "skipped": self.skipped}


def owned_folders(user, ids) -> list[Folder]:
    """Live folders from `ids` that belong to `user`, in a stable order."""
    return list(Folder.objects.filter(pk__in=ids, owner=user, deleted_at__isnull=True)
                .order_by("name", "pk"))


def owned_books(user, ids) -> list[Book]:
    return list(Book.objects.filter(pk__in=ids, owner=user, deleted_at__isnull=True)
                .order_by("title", "pk"))


def _without_nested(folders: list[Folder]) -> tuple[list[Folder], list[Folder]]:
    """Split off folders that sit beneath another folder in the same selection.

    Moving a folder and something inside it would pull the child *out* of the
    parent it just travelled with — two clicks producing a shape nobody asked
    for. The library only ever shows one level at a time so this cannot happen
    from the interface, but the endpoint takes whatever it is given.
    """
    selected = {f.pk for f in folders}
    top, nested = [], []
    for folder in folders:
        if selected & {a.pk for a in folder.ancestors()}:
            nested.append(folder)
        else:
            top.append(folder)
    return top, nested


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

def move(user, folder_ids, book_ids, target: Folder | None) -> BulkResult:
    result = BulkResult()

    folders, nested = _without_nested(owned_folders(user, folder_ids))
    for folder in nested:
        result.skip("folder", folder.pk, "Moves with the folder it is in.")

    for folder in folders:
        if target is not None and folder.pk == target.pk:
            result.skip("folder", folder.pk, "A folder cannot be moved inside itself.")
            continue
        folder.parent = target
        try:
            with transaction.atomic():
                folder.full_clean(exclude=["owner"])
                folder.save(update_fields=["parent", "updated_at"])
        except DjangoValidationError as exc:
            result.skip("folder", folder.pk, "; ".join(sum(exc.message_dict.values(), [])))
        except IntegrityError:
            result.skip("folder", folder.pk, "A folder with that name is already there.")
        else:
            result.folders += 1

    # No name collision to guard against here: two books may share a title in
    # one folder, which is what makes filing the same PDF twice legal.
    for book in owned_books(user, book_ids):
        book.folder = target
        book.save(update_fields=["folder", "updated_at"])
        result.books += 1

    return result


def trash(user, folder_ids, book_ids) -> BulkResult:
    result = BulkResult()

    # Folders first, and their contents go with them. A book that was selected
    # *and* sits in a selected folder is then already gone, which is why the
    # book pass re-reads what is still live rather than trusting the id list.
    for folder in owned_folders(user, folder_ids):
        counts = folder.trash()
        result.folders += counts["folders"]
        result.books += counts["books"]

    for book in owned_books(user, book_ids):
        book.trash()
        result.books += 1

    return result


def set_favourite(user, book_ids, value: bool) -> BulkResult:
    result = BulkResult()
    for book in owned_books(user, book_ids):
        state, _ = UserBookState.objects.get_or_create(user=user, book=book)
        if state.is_favourite != value:
            state.is_favourite = value
            state.save(update_fields=["is_favourite", "updated_at"])
        result.books += 1
    return result


def add_to_collection(user, book_ids, collection) -> BulkResult:
    result = BulkResult()
    for book in owned_books(user, book_ids):
        _, created = CollectionBook.objects.get_or_create(collection=collection, book=book)
        if created:
            result.books += 1
        else:
            result.skip("book", book.pk, "Already in that collection.")
    return result
