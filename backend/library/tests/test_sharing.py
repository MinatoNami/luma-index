"""Sharing.

The permission matrix from docs/phases/07-hardening.md, plus the deletion rules
§33 leaves undefined. The tests that matter are the ones asserting what a
non-owner may *not* see.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from library.lifecycle import readers_of, set_visibility
from library.models import Book, Bookmark, Folder, Highlight, ReadingProgress, ShareAudit
from library.permissions import can_modify, can_read, readable_books

from .pdfs import make_pdf


@pytest.fixture
def book(api, user):
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Shared.pdf", make_pdf(pages=6))]},
             headers=api.headers)
    return Book.objects.get()


@pytest.fixture
def reader(other_user):
    """A second signed-in user who owns nothing."""
    client = Client()
    client.force_login(other_user)
    client.get(reverse("accounts:csrf"))
    client.headers = {"x-csrftoken": client.cookies["lumaindex_csrftoken"].value}
    return client


def share(book, actor):
    return set_visibility(book, actor, Book.Visibility.SHARED)


# -- the rule itself ------------------------------------------------------------ #

@pytest.mark.django_db
def test_private_books_are_readable_only_by_their_owner(book, user, other_user):
    assert can_read(user, book) is True
    assert can_read(other_user, book) is False


@pytest.mark.django_db
def test_shared_books_are_readable_by_any_signed_in_user(book, user, other_user):
    share(book, user)
    assert can_read(other_user, book) is True


@pytest.mark.django_db
def test_only_the_owner_may_modify(book, user, other_user):
    share(book, user)
    assert can_modify(user, book) is True
    assert can_modify(other_user, book) is False


@pytest.mark.django_db
def test_a_trashed_book_is_hidden_even_from_people_it_was_shared_with(book, user, other_user):
    share(book, user)
    book.trash()
    book.refresh_from_db()
    assert can_read(other_user, book) is False
    assert can_read(user, book) is True, "the owner still sees it in their trash"


@pytest.mark.django_db
def test_readable_books_covers_owned_and_shared(book, user, other_user):
    theirs = Book.objects.create(owner=other_user, title="Theirs",
                                 visibility=Book.Visibility.SHARED)
    Book.objects.create(owner=other_user, title="Theirs, private")

    readable = set(readable_books(user).values_list("title", flat=True))
    assert readable == {book.title, theirs.title}


# -- the endpoints ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_reader_can_open_a_shared_book(api, book, user, reader):
    share(book, user)
    for name in ("library:book-detail", "library:book-content", "library:book-outline"):
        assert reader.get(reverse(name, args=[book.pk])).status_code == 200, name


@pytest.mark.django_db
def test_a_reader_cannot_open_a_private_book(book, reader):
    for name in ("library:book-detail", "library:book-content", "library:book-outline"):
        # 404, not 403: a 403 would confirm the book exists.
        assert reader.get(reverse(name, args=[book.pk])).status_code == 404, name


@pytest.mark.django_db
def test_a_reader_cannot_rename_or_delete_a_shared_book(api, book, user, reader):
    share(book, user)

    renamed = reader.patch(reverse("library:book-detail", args=[book.pk]),
                           {"title": "Mine now"}, content_type="application/json",
                           headers=reader.headers)
    deleted = reader.delete(reverse("library:book-detail", args=[book.pk]),
                            headers=reader.headers)

    assert renamed.status_code == 404
    assert deleted.status_code == 404
    book.refresh_from_db()
    assert book.title == "Shared" and book.deleted_at is None


@pytest.mark.django_db
def test_a_reader_cannot_change_sharing(api, book, user, reader):
    share(book, user)
    response = reader.post(reverse("library:book-share", args=[book.pk]),
                           {"visibility": "private"}, content_type="application/json",
                           headers=reader.headers)
    assert response.status_code == 404
    book.refresh_from_db()
    assert book.visibility == Book.Visibility.SHARED


@pytest.mark.django_db
def test_shared_with_me_lists_other_peoples_books_only(api, book, user, reader, other_user):
    share(book, user)
    own = Book.objects.create(owner=other_user, title="Their own",
                              visibility=Book.Visibility.SHARED)

    listed = reader.get(reverse("library:shared")).json()
    titles = [b["title"] for b in listed]
    assert book.title in titles
    assert own.title not in titles, "your own book is not 'shared with me'"


@pytest.mark.django_db
def test_a_reader_never_sees_the_owners_filenames_or_folders(api, book, user, reader):
    """The path describes the owner's organisation, not the book (PRD §16)."""
    folder = Folder.objects.create(owner=user, name="Private Folder Name")
    book.folder = folder
    book.save(update_fields=["folder"])
    share(book, user)

    body = reader.get(reverse("library:shared")).json()[0]
    raw = str(body)
    assert "Private Folder Name" not in raw
    assert "Shared.pdf" not in raw
    assert "source" not in body and "path" not in body


# -- per-reader state --------------------------------------------------------------- #

@pytest.mark.django_db
def test_each_reader_keeps_their_own_progress(api, book, user, reader, other_user):
    """PRD §19: sharing a book shares the file, never the place you got to."""
    from library.services import process_pending_documents

    process_pending_documents()   # gives the book a page count
    share(book, user)

    api.put(reverse("library:book-progress", args=[book.pk]),
            {"page": 4, "page_fraction": 0}, content_type="application/json",
            headers=api.headers)
    reader.put(reverse("library:book-progress", args=[book.pk]),
               {"page": 1, "page_fraction": 0}, content_type="application/json",
               headers=reader.headers)

    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 4
    assert reader.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 1


@pytest.mark.django_db
def test_readers_cannot_see_each_others_annotations(api, book, user, reader):
    share(book, user)
    quads = {"v": 1, "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]}

    api.post(reverse("library:highlights", args=[book.pk]),
             {"page": 0, "position_data": quads, "selected_text": "owner's"},
             content_type="application/json", headers=api.headers)
    reader.post(reverse("library:highlights", args=[book.pk]),
                {"page": 0, "position_data": quads, "selected_text": "reader's"},
                content_type="application/json", headers=reader.headers)

    owner_sees = api.get(reverse("library:highlights", args=[book.pk])).json()
    reader_sees = reader.get(reverse("library:highlights", args=[book.pk])).json()

    assert [h["selected_text"] for h in owner_sees] == ["owner's"]
    assert [h["selected_text"] for h in reader_sees] == ["reader's"]


# -- the deletion matrix -------------------------------------------------------------- #

@pytest.mark.django_db
def test_unsharing_keeps_other_readers_annotations(api, book, user, reader, other_user):
    """The decision §33 leaves open.

    An accidental toggle must not destroy someone else's work, and re-sharing
    has to bring it back exactly as it was.
    """
    share(book, user)
    reader.post(reverse("library:bookmarks", args=[book.pk]), {"page": 2},
                content_type="application/json", headers=reader.headers)

    set_visibility(book, user, Book.Visibility.PRIVATE)

    assert reader.get(reverse("library:bookmarks", args=[book.pk])).status_code == 404
    assert Bookmark.objects.filter(user=other_user, book=book).exists(), \
        "un-sharing destroyed another reader's bookmark"

    share(book, user)
    assert len(reader.get(reverse("library:bookmarks", args=[book.pk])).json()) == 1


@pytest.mark.django_db
def test_deleting_the_book_removes_everyones_annotations(api, book, user, reader):
    """Different from un-sharing: there is nothing left to point at."""
    share(book, user)
    reader.post(reverse("library:bookmarks", args=[book.pk]), {"page": 2},
                content_type="application/json", headers=reader.headers)

    book.delete()
    assert not Bookmark.objects.filter(book_id=book.pk).exists()


@pytest.mark.django_db
def test_a_disabled_owner_does_not_hide_their_shared_books(api, book, user, reader):
    """Disabling is an administrative action about signing in, not a takedown."""
    share(book, user)
    user.is_active = False
    user.save(update_fields=["is_active"])

    assert reader.get(reverse("library:book-content", args=[book.pk])).status_code == 200


@pytest.mark.django_db
def test_deleting_the_owners_account_removes_the_shared_books(api, book, user, reader):
    share(book, user)
    user.delete()
    assert reader.get(reverse("library:book-detail", args=[book.pk])).status_code == 404


# -- audit and counts -------------------------------------------------------------- #

@pytest.mark.django_db
def test_visibility_changes_are_recorded(book, user):
    share(book, user)
    set_visibility(book, user, Book.Visibility.PRIVATE)

    events = list(ShareAudit.objects.filter(book=book).order_by("created_at")
                  .values_list("from_visibility", "to_visibility"))
    assert events == [("private", "shared"), ("shared", "private")]


@pytest.mark.django_db
def test_setting_the_same_visibility_records_nothing(book, user):
    set_visibility(book, user, Book.Visibility.PRIVATE)
    assert not ShareAudit.objects.filter(book=book).exists()


@pytest.mark.django_db
def test_other_readers_are_counted_before_an_irreversible_change(api, book, user,
                                                                 reader, other_user):
    share(book, user)
    ReadingProgress.objects.create(user=other_user, book=book, page=2, percentage=20)

    assert list(readers_of(book)) == [other_user]
    body = api.get(reverse("library:book-share", args=[book.pk])).json()
    assert body["other_readers"] == 1
    assert body["visibility"] == "shared"


@pytest.mark.django_db
def test_the_owner_is_not_counted_as_another_reader(api, book, user):
    Highlight.objects.create(user=user, book=book, page=0,
                             position_data={"v": 1, "quads": []})
    assert readers_of(book).count() == 0
