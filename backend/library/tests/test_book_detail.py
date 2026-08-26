"""The detail shape: what one book carries that a listing does not.

Two fields exist here rather than on BookSerializer because a grid of a hundred
covers shows neither and would pay for both. The tests that matter are the ones
about where they are *not*: absent from the listing, and absent from what a
reader of a shared book is told about someone else's filing.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from library.models import (
    Book,
    Bookmark,
    BookSource,
    Collection,
    CollectionBook,
    Folder,
    Highlight,
    PageNote,
)

User = get_user_model()
PASSWORD = "a-long-enough-password-42"


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def stranger(db):
    return User.objects.create_user(email="stranger@example.com", password=PASSWORD)


@pytest.fixture
def book(owner):
    folder = Folder.objects.create(owner=owner, name="Shelf")
    b = Book.objects.create(owner=owner, folder=folder, title="A Book")
    BookSource.objects.create(book=b, storage_key=f"{b.pk:064d}",
                              original_filename="a-book.pdf", file_size=4096)
    return b


def detail(client, b):
    return client.get(reverse("library:book-detail", args=[b.pk])).json()


@pytest.mark.django_db
def test_the_detail_says_which_collections_a_book_is_in(owner, book):
    for name in ("Reading this year", "Reference"):
        collection = Collection.objects.create(owner=owner, name=name)
        CollectionBook.objects.create(collection=collection, book=book)

    body = detail(signed_in(owner), book)

    assert {c["name"] for c in body["collections"]} == {"Reading this year", "Reference"}
    assert all(isinstance(c["id"], int) for c in body["collections"])


@pytest.mark.django_db
def test_a_book_in_nothing_says_so_with_an_empty_list(owner, book):
    assert detail(signed_in(owner), book)["collections"] == []


@pytest.mark.django_db
def test_the_detail_counts_what_you_have_written(owner, book):
    Bookmark.objects.create(user=owner, book=book, page=3)
    for page in (1, 2):
        Highlight.objects.create(
            user=owner, book=book, page=page, selected_text=f"p{page}",
            position_data={"v": 1, "page": page,
                           "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]})

    assert detail(signed_in(owner), book)["annotations"] == {
        "bookmarks": 1, "highlights": 2, "notes": 0,
    }


@pytest.mark.django_db
def test_the_counts_are_yours_and_not_everybody_s(owner, stranger, book):
    """A shared book is read by several people; the number on your page is the
    number of things you wrote."""
    book.visibility = Book.Visibility.SHARED
    book.save(update_fields=["visibility"])

    PageNote.objects.create(user=owner, book=book, page=1, body="mine")
    for page in (1, 2, 3):
        PageNote.objects.create(user=stranger, book=book, page=page, body="theirs")

    assert detail(signed_in(owner), book)["annotations"]["notes"] == 1


@pytest.mark.django_db
def test_the_listing_carries_neither(owner, book):
    """Both cost a query each, and a grid of covers shows neither."""
    collection = Collection.objects.create(owner=owner, name="Reading this year")
    CollectionBook.objects.create(collection=collection, book=book)

    row = signed_in(owner).get(reverse("library:books")).json()["results"][0]

    assert "collections" not in row
    assert "annotations" not in row


@pytest.mark.django_db
def test_a_reader_of_a_shared_book_is_not_told_the_owner_s_filing(owner, stranger, book):
    """Which collections the owner keeps it in describes their organisation,
    not the book — the same reason they never see the folder path."""
    book.visibility = Book.Visibility.SHARED
    book.save(update_fields=["visibility"])
    collection = Collection.objects.create(owner=owner, name="Secret Project")
    CollectionBook.objects.create(collection=collection, book=book)

    body = detail(signed_in(stranger), book)

    assert "collections" not in body
    assert "Secret Project" not in str(body)


@pytest.mark.django_db
def test_the_detail_does_not_cost_a_query_per_collection(owner, book):
    """The point of the field.

    The collection picker used to answer this by asking every collection
    whether it held this book, one request each. Reading it off the book has to
    stay one query however many collections there are, or it is the same bug in
    a different place.
    """
    client = signed_in(owner)
    detail(client, book)  # warm any lazily-loaded session/user rows

    with CaptureQueriesContext(connection) as few:
        detail(client, book)

    for i in range(12):
        collection = Collection.objects.create(owner=owner, name=f"Shelf {i}")
        CollectionBook.objects.create(collection=collection, book=book)

    with CaptureQueriesContext(connection) as many:
        body = detail(client, book)

    assert len(body["collections"]) == 12
    assert len(many) == len(few), (
        f"{len(few)} queries with no collections, {len(many)} with twelve"
    )
