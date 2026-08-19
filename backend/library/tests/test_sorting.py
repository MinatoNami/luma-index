"""One sort order across folders, books, and the trash.

Folders and books live in different tables with different column names, so what
is worth pinning down is that the same word means the same thing in each
listing — and that a word one of them does not have falls back rather than
returning a 500 to somebody who typed a query string.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from library.models import Book, BookSource, Folder
from library.sorting import BOOK_FIELDS, FOLDER_FIELDS, order_by


def at(days_ago):
    return timezone.now() - timedelta(days=days_ago)


def a_folder(user, name, *, added=None, trashed=None):
    folder = Folder.objects.create(owner=user, name=name, deleted_at=trashed)
    if added:
        Folder.objects.filter(pk=folder.pk).update(created_at=added)
    return folder


def a_book(user, title, *, added=None, size=10, trashed=None):
    book = Book.objects.create(owner=user, title=title, deleted_at=trashed)
    BookSource.objects.create(book=book, storage_key=f"{book.pk:064d}",
                              original_filename=f"{title}.pdf", file_size=size)
    if added:
        Book.objects.filter(pk=book.pk).update(created_at=added)
    return book


def names(rows):
    return [r.get("name") or r.get("title") for r in rows]


# -- the vocabulary --------------------------------------------------------------- #

def test_a_bare_key_sorts_ascending():
    assert order_by("added", BOOK_FIELDS) == ["created_at", "pk"]


def test_a_leading_minus_sorts_descending():
    assert order_by("-added", BOOK_FIELDS) == ["-created_at", "pk"]


def test_the_same_word_reaches_each_tables_own_column():
    assert order_by("name", FOLDER_FIELDS)[0] == "name"
    assert order_by("name", BOOK_FIELDS)[0] == "title"


def test_a_field_a_table_does_not_have_falls_back(user):
    """Folders have no size. Typing one into a query string should not be a
    server error."""
    assert order_by("size", FOLDER_FIELDS) == ["name", "pk"]


def test_nonsense_falls_back_rather_than_failing():
    assert order_by("'; drop table", BOOK_FIELDS) == ["title", "pk"]
    assert order_by(None, BOOK_FIELDS) == ["title", "pk"]
    assert order_by("-", BOOK_FIELDS) == ["-title", "pk"]


def test_every_sort_has_a_tie_break():
    """Two books added in the same second would otherwise come back in whatever
    order the database felt like, and a listing that reshuffles between
    refreshes looks broken."""
    for key in BOOK_FIELDS:
        assert order_by(key, BOOK_FIELDS)[-1] == "pk"


# -- through the API ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_books_sort_by_name_by_default(api, user):
    a_book(user, "Zebra")
    a_book(user, "Alpha")

    body = api.get(reverse("library:books")).json()

    assert names(body) == ["Alpha", "Zebra"]


@pytest.mark.django_db
def test_books_sort_by_when_they_were_added(api, user):
    a_book(user, "Old", added=at(30))
    a_book(user, "New", added=at(1))

    assert names(api.get(reverse("library:books"), {"sort": "added"}).json()) == ["Old", "New"]
    assert names(api.get(reverse("library:books"), {"sort": "-added"}).json()) == ["New", "Old"]


@pytest.mark.django_db
def test_books_sort_by_size(api, user):
    a_book(user, "Small", size=10)
    a_book(user, "Large", size=9000)

    assert names(api.get(reverse("library:books"), {"sort": "-size"}).json()) == ["Large", "Small"]


@pytest.mark.django_db
def test_folders_sort_by_name_by_default(api, user):
    a_folder(user, "Zebra")
    a_folder(user, "Alpha")

    assert names(api.get(reverse("library:folders")).json()) == ["Alpha", "Zebra"]


@pytest.mark.django_db
def test_folders_sort_by_when_they_were_added(api, user):
    a_folder(user, "Old", added=at(30))
    a_folder(user, "New", added=at(1))

    body = api.get(reverse("library:folders"), {"sort": "-added"}).json()

    assert names(body) == ["New", "Old"]


@pytest.mark.django_db
def test_a_folder_sort_a_folder_cannot_do_falls_back_to_name(api, user):
    a_folder(user, "Zebra")
    a_folder(user, "Alpha")

    body = api.get(reverse("library:folders"), {"sort": "-size"}).json()

    assert names(body) == ["Alpha", "Zebra"], "not a 500"


# -- the trash ----------------------------------------------------------------------- #

@pytest.mark.django_db
def test_the_trash_shows_the_most_recently_deleted_first(api, user):
    """What you are looking for in a trash is almost always the thing you just
    deleted by mistake."""
    a_book(user, "Long gone", trashed=at(40))
    a_book(user, "Just now", trashed=at(0))
    a_folder(user, "Older folder", trashed=at(20))
    a_folder(user, "Newer folder", trashed=at(2))

    body = api.get(reverse("library:trash")).json()

    assert names(body["books"]) == ["Just now", "Long gone"]
    assert names(body["folders"]) == ["Newer folder", "Older folder"]


@pytest.mark.django_db
def test_the_trash_can_be_sorted_by_name_instead(api, user):
    a_book(user, "Zebra", trashed=at(1))
    a_book(user, "Alpha", trashed=at(40))

    body = api.get(reverse("library:trash"), {"sort": "name"}).json()

    assert names(body["books"]) == ["Alpha", "Zebra"]


@pytest.mark.django_db
def test_the_trash_reports_the_retention_policy(api, user, settings):
    settings.TRASH_RETENTION_DAYS = 30

    assert api.get(reverse("library:trash")).json()["retention_days"] == 30


@pytest.mark.django_db
def test_the_trash_reports_no_policy_when_retention_is_off(api, user, settings):
    settings.TRASH_RETENTION_DAYS = 0

    assert api.get(reverse("library:trash")).json()["retention_days"] is None


@pytest.mark.django_db
def test_a_trashed_item_carries_when_it_will_be_destroyed(api, user, settings):
    settings.TRASH_RETENTION_DAYS = 30
    a_book(user, "Doomed", trashed=at(10))

    body = api.get(reverse("library:trash")).json()

    assert body["books"][0]["expires_at"] is not None


@pytest.mark.django_db
def test_a_live_item_has_no_expiry(api, user, settings):
    settings.TRASH_RETENTION_DAYS = 30
    a_book(user, "Kept")

    assert api.get(reverse("library:books")).json()[0]["expires_at"] is None
