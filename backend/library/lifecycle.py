"""What happens to other people's data when an owner acts.

PRD §33 says account deletion "must define what happens to books previously
shared by that user" and then does not define it. This module is that
definition, kept in one place so the answers can be read together rather than
inferred from scattered `on_delete` arguments.

| Event                     | Owner's data      | Other readers' annotations |
| ------------------------- | ----------------- | -------------------------- |
| Owner deletes account     | removed           | removed with the book      |
| Owner disabled by admin   | retained          | retained and readable      |
| SHARED -> PRIVATE         | retained          | **retained**, inaccessible |
| Owner deletes one book    | removed           | removed with the book      |
| Stored file goes missing  | source flagged    | untouched                  |
| Owner empties their trash | removed           | removed with the book      |

The one that matters is the third. Un-sharing must not destroy what other
people wrote: an accidental toggle would otherwise be unrecoverable, and
re-sharing restores their notes exactly as they were. Deletion of the book
itself is different — there is nothing left for an annotation to point at.
"""

from __future__ import annotations

import logging

from django.db import transaction

from .models import Book, ShareAudit

logger = logging.getLogger("lumaindex.sharing")


@transaction.atomic
def set_visibility(book: Book, actor, visibility: str) -> Book:
    """Change a book's visibility and record who did it."""
    previous = book.visibility
    if previous == visibility:
        return book

    book.visibility = visibility
    book.save(update_fields=["visibility", "updated_at"])
    ShareAudit.objects.create(book=book, actor=actor,
                              from_visibility=previous, to_visibility=visibility)

    # Deliberately nothing else. Other readers' progress and annotations stay
    # exactly where they are, so re-sharing restores them.
    logger.info("visibility changed",
                extra={"event": "sharing.visibility", "book_id": book.pk,
                       "from": previous, "to": visibility})
    return book


def readers_of(book: Book):
    """Everyone other than the owner who has reading state on this book.

    Used to say "3 other people have notes on this" before an owner does
    something irreversible.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.filter(
        pk__in=(
            list(book.progress_records.values_list("user_id", flat=True))
            + list(book.highlights.values_list("user_id", flat=True))
            + list(book.bookmarks.values_list("user_id", flat=True))
            + list(book.page_notes.values_list("user_id", flat=True))
        )
    ).exclude(pk=book.owner_id).distinct()
