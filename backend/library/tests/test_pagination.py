"""Every library list is bounded, and says how much it left out.

Phase 3 wrote the rule and the code never kept it, which is the sort of thing
that only shows up on somebody else's library. These tests are mostly about the
`count`: a cap without one is indistinguishable from a short list.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from library.models import Book, BookSource, Collection, CollectionBook, Folder

User = get_user_model()
PASSWORD = "a-long-enough-password-42"


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.headers = {"x-csrftoken": client.cookies["lumaindex_csrftoken"].value}
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password=PASSWORD)


def make_books(owner, count, folder=None):
    books = []
    for i in range(count):
        book = Book.objects.create(owner=owner, folder=folder, title=f"Book {i:03d}")
        BookSource.objects.create(book=book, storage_key=f"{book.pk:064d}",
                                  original_filename=f"book-{i}.pdf", file_size=1024)
        books.append(book)
    return books


@pytest.mark.django_db
def test_the_book_list_is_bounded_and_reports_the_total(owner):
    make_books(owner, 12)
    body = signed_in(owner).get(reverse("library:books"), {"limit": 5}).json()

    assert len(body["results"]) == 5
    assert body["count"] == 12, "the client cannot page without knowing the total"
    assert body["limit"] == 5 and body["offset"] == 0


@pytest.mark.django_db
def test_offset_walks_the_whole_list_without_repeating(owner):
    make_books(owner, 7)
    client = signed_in(owner)
    seen: list[int] = []
    for offset in range(0, 7, 3):
        page = client.get(reverse("library:books"),
                          {"limit": 3, "offset": offset, "sort": "name"}).json()
        seen.extend(b["id"] for b in page["results"])

    assert len(seen) == 7
    assert len(set(seen)) == 7, "a page boundary repeated or dropped a book"


@pytest.mark.django_db
def test_a_silly_limit_falls_back_instead_of_failing(owner):
    make_books(owner, 3)
    client = signed_in(owner)

    for raw in ("banana", "", "-4", "0"):
        response = client.get(reverse("library:books"), {"limit": raw})
        assert response.status_code == 200, f"limit={raw!r} broke the listing"
        assert response.json()["limit"] >= 1


@pytest.mark.django_db
def test_the_limit_is_capped_however_much_you_ask_for(owner):
    body = signed_in(owner).get(reverse("library:books"), {"limit": 100_000}).json()
    assert body["limit"] == 500, "an unbounded limit is an unpaginated endpoint"


@pytest.mark.django_db
def test_folders_are_bounded_too(owner):
    for i in range(6):
        Folder.objects.create(owner=owner, name=f"Folder {i}")
    body = signed_in(owner).get(reverse("library:folders"), {"limit": 2}).json()
    assert len(body["results"]) == 2 and body["count"] == 6


@pytest.mark.django_db
def test_the_trash_bounds_both_halves_and_counts_them(owner):
    for book in make_books(owner, 5):
        book.trash()
    for i in range(3):
        Folder.objects.create(owner=owner, name=f"Gone {i}").trash()

    body = signed_in(owner).get(reverse("library:trash"), {"limit": 2}).json()
    assert len(body["books"]) == 2 and body["book_count"] == 5
    assert len(body["folders"]) == 2 and body["folder_count"] == 3


@pytest.mark.django_db
def test_books_in_a_collection_are_bounded(owner):
    collection = Collection.objects.create(owner=owner, name="Everything")
    for book in make_books(owner, 4):
        CollectionBook.objects.create(collection=collection, book=book)

    body = signed_in(owner).get(
        reverse("library:collection-books", args=[collection.pk]), {"limit": 1}).json()
    assert len(body["results"]) == 1 and body["count"] == 4


@pytest.mark.django_db
def test_continue_reading_still_answers(owner):
    """It builds a list rather than a queryset, so paginating it raised
    TypeError on `.count()` — and it was already capped upstream anyway."""
    response = signed_in(owner).get(reverse("library:continue-reading"))
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.django_db
def test_annotations_are_bounded_but_reachable(owner):
    """Bounded, and every one still reachable.

    The reader draws overlays by filtering the highlights it holds by page, so
    a client that stopped at the first slice would stop showing highlights on
    later pages rather than showing a short list. Walking the offsets has to
    return every row exactly once.
    """
    from library.models import Highlight

    book = make_books(owner, 1)[0]
    for i in range(280):
        Highlight.objects.create(
            user=owner, book=book, page=i, selected_text=f"passage {i}",
            position_data={"v": 1, "page": i,
                           "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]})

    client = signed_in(owner)
    url = reverse("library:highlights", args=[book.pk])

    first = client.get(url).json()
    assert first["count"] == 280
    assert len(first["results"]) == 250, "the default slice should bound one response"

    seen: list[int] = [h["id"] for h in first["results"]]
    while len(seen) < first["count"]:
        page = client.get(url, {"offset": len(seen)}).json()
        assert page["results"], "paging stalled before the end"
        seen.extend(h["id"] for h in page["results"])

    assert len(seen) == 280
    assert len(set(seen)) == 280, "a page boundary repeated or dropped a highlight"


@pytest.mark.django_db
def test_filtering_annotations_by_page_still_works(owner):
    from library.models import Highlight

    book = make_books(owner, 1)[0]
    for i in range(4):
        Highlight.objects.create(
            user=owner, book=book, page=i % 2, selected_text=f"p{i}",
            position_data={"v": 1, "page": i % 2,
                           "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]})

    body = signed_in(owner).get(
        reverse("library:highlights", args=[book.pk]), {"page": 1}).json()
    assert body["count"] == 2
    assert all(h["page"] == 1 for h in body["results"])
