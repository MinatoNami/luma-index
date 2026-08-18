"""Who may read a book.

PRD §16 keeps this to two states, and §43 lists the richer model as future
work. The whole decision therefore lives in one function: when INSTANCE_SHARED,
USER_SHARED and groups arrive, this is the only place that changes, and it is
the one place to test.

Nothing else in the codebase should compare `visibility` directly.
"""

from __future__ import annotations

from django.db.models import Q

from .models import Book


def can_read(user, book: Book) -> bool:
    """True if `user` may open this book."""
    if not user or not user.is_authenticated:
        return False
    if book.deleted_at is not None:
        # A trashed book is invisible even to people it was shared with; only
        # the owner can see it, and only in their trash.
        return book.owner_id == user.pk
    if book.owner_id == user.pk:
        return True
    return book.visibility == Book.Visibility.SHARED


def can_modify(user, book: Book) -> bool:
    """Only the owner changes a book. Readers get their own annotations."""
    return bool(user and user.is_authenticated and book.owner_id == user.pk)


def readable_books(user):
    """Every book `user` may open — theirs, plus anything shared with the instance.

    The single queryset every library view builds on, so a permission fix
    happens once rather than per view.
    """
    if not user or not user.is_authenticated:
        return Book.objects.none()
    return Book.objects.filter(
        Q(owner=user) | Q(visibility=Book.Visibility.SHARED, deleted_at__isnull=True)
    )
