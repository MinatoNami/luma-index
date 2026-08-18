"""Folder tree and trash semantics."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from library.models import MAX_FOLDER_DEPTH, Book, BookSource, Folder


def folder(owner, name, parent=None) -> Folder:
    return Folder.objects.create(owner=owner, name=name, parent=parent)


def book(owner, title, folder=None) -> Book:
    created = Book.objects.create(owner=owner, title=title, folder=folder)
    BookSource.objects.create(book=created, storage_key="a" * 64,
                              original_filename=f"{title}.pdf", file_size=100)
    return created


# -- tree ---------------------------------------------------------------------- #

@pytest.mark.django_db
def test_path_reads_root_first(user):
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    python = folder(user, "Python", programming)
    assert python.path == "Books/Programming/Python"


@pytest.mark.django_db
def test_descendants_are_found(user):
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    python = folder(user, "Python", programming)
    folder(user, "Fiction", books)
    assert set(books.descendant_ids()) >= {programming.pk, python.pk}


@pytest.mark.django_db
def test_two_folders_cannot_share_a_name_in_one_parent(user):
    books = folder(user, "Books")
    folder(user, "Programming", books)
    with pytest.raises(IntegrityError):
        folder(user, "Programming", books)


@pytest.mark.django_db
def test_two_folders_cannot_share_a_name_at_the_root(user):
    """PostgreSQL treats NULL parents as distinct, so this needs its own constraint."""
    folder(user, "Books")
    with pytest.raises(IntegrityError):
        folder(user, "Books")


@pytest.mark.django_db
def test_different_users_may_use_the_same_folder_name(user, other_user):
    folder(user, "Books")
    folder(other_user, "Books")  # must not raise


@pytest.mark.django_db
def test_a_trashed_name_does_not_block_reuse(user):
    """A partial unique index: the constraint applies only to live folders."""
    first = folder(user, "Books")
    first.trash()
    folder(user, "Books")  # must not raise


# -- move validation ------------------------------------------------------------ #

@pytest.mark.django_db
def test_a_folder_cannot_be_its_own_parent(user):
    books = folder(user, "Books")
    books.parent = books
    with pytest.raises(ValidationError):
        books.clean()


@pytest.mark.django_db
def test_a_folder_cannot_move_inside_its_own_subfolder(user):
    """Otherwise the subtree detaches and every ancestor walk loops forever."""
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    books.parent = programming
    with pytest.raises(ValidationError):
        books.clean()


@pytest.mark.django_db
def test_a_folder_cannot_move_under_another_users_folder(user, other_user):
    mine = folder(user, "Books")
    theirs = folder(other_user, "Theirs")
    mine.parent = theirs
    with pytest.raises(ValidationError):
        mine.clean()


@pytest.mark.django_db
def test_nesting_is_capped(user):
    """MAX_FOLDER_DEPTH levels are allowed; the one after that is not."""
    parent = None
    for depth in range(MAX_FOLDER_DEPTH):
        parent = folder(user, f"level-{depth}", parent)

    assert parent.depth == MAX_FOLDER_DEPTH - 1

    too_deep = Folder(owner=user, name="one-too-many", parent=parent)
    with pytest.raises(ValidationError):
        too_deep.clean()


# -- trash ----------------------------------------------------------------------- #

@pytest.mark.django_db
def test_trashing_a_folder_trashes_its_contents(user):
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    inner = book(user, "DDIA", programming)

    counts = books.trash()

    assert counts == {"folders": 2, "books": 1}
    assert Folder.objects.live().count() == 0
    assert Book.objects.live().count() == 0
    # Trashed, not deleted.
    assert Book.objects.filter(pk=inner.pk).exists()


@pytest.mark.django_db
def test_restoring_a_folder_brings_back_what_went_with_it(user):
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    book(user, "DDIA", programming)

    books.trash()
    books.refresh_from_db()
    counts = books.restore()

    assert counts == {"folders": 2, "books": 1}
    assert Folder.objects.live().count() == 2
    assert Book.objects.live().count() == 1


@pytest.mark.django_db
def test_restoring_does_not_resurrect_separately_deleted_items(user):
    """A book deleted last week should stay deleted when a folder comes back."""
    books = folder(user, "Books")
    earlier = book(user, "Deleted earlier", books)
    later = book(user, "Deleted with the folder", books)

    earlier.trash()
    books.trash()
    books.refresh_from_db()
    books.restore()

    earlier.refresh_from_db()
    later.refresh_from_db()
    assert earlier.deleted_at is not None, "a separately deleted book came back"
    assert later.deleted_at is None


@pytest.mark.django_db
def test_a_book_cannot_be_restored_into_a_trashed_folder(user):
    books = folder(user, "Books")
    inner = book(user, "DDIA", books)
    books.trash()
    inner.refresh_from_db()

    with pytest.raises(ValidationError):
        inner.restore()


@pytest.mark.django_db
def test_a_folder_cannot_be_restored_under_a_trashed_parent(user):
    books = folder(user, "Books")
    programming = folder(user, "Programming", books)
    books.trash()
    programming.refresh_from_db()
    # Detach it from the group restore so it is trashed "on its own".
    programming.deleted_at = programming.deleted_at.replace(microsecond=123)
    programming.save(update_fields=["deleted_at"])

    with pytest.raises(ValidationError):
        programming.restore()


@pytest.mark.django_db
def test_books_are_private_by_default(user):
    assert book(user, "DDIA").visibility == Book.Visibility.PRIVATE


@pytest.mark.django_db
def test_book_path_includes_its_folders(user):
    books = folder(user, "Books")
    fiction = folder(user, "Fiction", books)
    assert book(user, "Dune", fiction).path == "Books/Fiction/Dune"
