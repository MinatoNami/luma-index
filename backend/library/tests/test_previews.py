"""Folder previews: which book covers stand in for a folder.

A folder has no picture of its own, so it borrows covers from the books inside
it. Nothing is stored, so there is no cache to go stale — but the *choice* of
covers is a real behaviour, and these pin it down.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from library.models import Book, Folder
from library.previews import PREVIEW_LIMIT, collect_preview_book_ids


def book(user, folder, title, *, cover=True, trashed=False):
    return Book.objects.create(
        owner=user, folder=folder, title=title,
        thumbnail_path=f"ab/cd/{title}.webp" if cover else "",
        deleted_at=timezone.now() if trashed else None,
    )


def previews_for(folder):
    return collect_preview_book_ids([folder])[folder.pk]


# -- what a folder borrows ------------------------------------------------------ #

@pytest.mark.django_db
def test_a_folder_borrows_the_covers_of_the_books_inside_it(user):
    folder = Folder.objects.create(owner=user, name="Django")
    ids = [book(user, folder, title).pk for title in ("Alpha", "Beta", "Gamma")]

    assert previews_for(folder) == ids, "shown in the order the folder lists them"


@pytest.mark.django_db
def test_only_the_first_few_covers_are_borrowed(user):
    folder = Folder.objects.create(owner=user, name="Big")
    ids = [book(user, folder, f"Book {n:02}").pk for n in range(20)]

    assert previews_for(folder) == ids[:PREVIEW_LIMIT]


@pytest.mark.django_db
def test_the_same_folder_shows_the_same_covers_every_time(user):
    """Books sharing a title must not reshuffle between requests — a mosaic
    that changes on every visit is not something a reader can recognise."""
    folder = Folder.objects.create(owner=user, name="Duplicated")
    ids = sorted(book(user, folder, "Same Title").pk for _ in range(6))

    assert previews_for(folder) == ids[:PREVIEW_LIMIT]


@pytest.mark.django_db
def test_a_book_still_being_processed_is_not_borrowed(user):
    """Covers arrive after the upload does. A book without one yet would render
    as a blank tile, so it is skipped in favour of one further down."""
    folder = Folder.objects.create(owner=user, name="Mixed")
    book(user, folder, "Aaa waiting for its cover", cover=False)
    ready = book(user, folder, "Zzz has a cover")

    assert previews_for(folder) == [ready.pk]


@pytest.mark.django_db
def test_a_trashed_book_is_not_borrowed(user):
    folder = Folder.objects.create(owner=user, name="Mixed")
    book(user, folder, "Aaa deleted", trashed=True)
    kept = book(user, folder, "Bbb kept")

    assert previews_for(folder) == [kept.pk]


@pytest.mark.django_db
def test_a_folder_with_nothing_in_it_borrows_nothing(user):
    folder = Folder.objects.create(owner=user, name="Empty")

    assert previews_for(folder) == []


# -- one level of lookahead ----------------------------------------------------- #

@pytest.mark.django_db
def test_a_folder_of_only_subfolders_borrows_from_them(user):
    """The shape every ZIP import produces at its root. Without lookahead this
    is exactly the folder that would show nothing at all."""
    outer = Folder.objects.create(owner=user, name="Ebooks")
    inner = Folder.objects.create(owner=user, name="Fiction", parent=outer)
    inside = book(user, inner, "A novel")

    assert previews_for(outer) == [inside.pk]


@pytest.mark.django_db
def test_a_parent_does_not_become_a_copy_of_its_first_subfolder(user):
    """Draining one subfolder would put two identical mosaics side by side in
    the same grid, which is worse than showing no picture at all."""
    outer = Folder.objects.create(owner=user, name="Ebooks")
    first = Folder.objects.create(owner=user, name="Aaa", parent=outer)
    second = Folder.objects.create(owner=user, name="Bbb", parent=outer)
    firsts = [book(user, first, f"A{n}").pk for n in range(4)]
    seconds = [book(user, second, f"B{n}").pk for n in range(4)]

    borrowed = collect_preview_book_ids([outer, first])
    assert borrowed[outer.pk] == [firsts[0], seconds[0], firsts[1], seconds[1]]
    assert borrowed[outer.pk] != borrowed[first.pk]


@pytest.mark.django_db
def test_direct_books_come_before_borrowed_ones(user):
    outer = Folder.objects.create(owner=user, name="Ebooks")
    inner = Folder.objects.create(owner=user, name="Sub", parent=outer)
    own = book(user, outer, "Zzz its own book")
    borrowed = book(user, inner, "Aaa a book below")

    assert previews_for(outer) == [own.pk, borrowed.pk]


@pytest.mark.django_db
def test_lookahead_stops_after_one_level(user):
    """Recursing would mean every upload invalidates the whole ancestor chain;
    one level is the line, so a grandchild's covers stay where they are."""
    outer = Folder.objects.create(owner=user, name="Top")
    middle = Folder.objects.create(owner=user, name="Middle", parent=outer)
    bottom = Folder.objects.create(owner=user, name="Bottom", parent=middle)
    book(user, bottom, "Too deep to borrow")

    assert previews_for(outer) == []
    assert previews_for(middle) != []


# -- cost ----------------------------------------------------------------------- #

@pytest.mark.django_db
def test_previews_cost_the_same_for_one_folder_or_fifty(user, django_assert_num_queries):
    """Three queries: direct books, subfolders, subfolder books. Per-folder
    lookups would make browsing quadratic in the number of folders."""
    folders = []
    for n in range(50):
        folder = Folder.objects.create(owner=user, name=f"Folder {n:02}")
        Folder.objects.create(owner=user, name="Sub", parent=folder)
        book(user, folder, f"Book {n:02}")
        folders.append(folder)

    with django_assert_num_queries(3):
        result = collect_preview_book_ids(folders)

    assert len(result) == 50


# -- through the API ------------------------------------------------------------ #

@pytest.mark.django_db
def test_a_folder_listing_carries_its_previews(api, user):
    folder = Folder.objects.create(owner=user, name="Django")
    expected = [book(user, folder, "Alpha").pk, book(user, folder, "Beta").pk]

    body = api.get(reverse("library:folders"), {"parent": "root"}).json()

    assert body[0]["preview_book_ids"] == expected


@pytest.mark.django_db
def test_a_single_folder_carries_its_previews_too(api, user):
    """The detail view renders one folder at a time, which takes the other
    branch of the batching cache."""
    outer = Folder.objects.create(owner=user, name="Ebooks")
    inner = Folder.objects.create(owner=user, name="Fiction", parent=outer)
    expected = book(user, inner, "A novel").pk

    body = api.get(reverse("library:folder-detail", args=[inner.pk])).json()

    assert body["preview_book_ids"] == [expected]
    assert body["ancestors"][0]["preview_book_ids"] == [expected], "borrowed by the parent"
