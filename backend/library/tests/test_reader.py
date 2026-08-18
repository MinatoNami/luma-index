"""Reading progress and outline extraction."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from library.models import Book, ReadingProgress
from library.services import process_pending_documents

from .pdfs import make_pdf


@pytest.fixture
def book(api):
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Book.pdf", make_pdf(pages=10))]},
             headers=api.headers)
    process_pending_documents()
    return Book.objects.get()


def put_progress(client, book, **payload):
    return client.put(reverse("library:book-progress", args=[book.pk]), payload,
                      content_type="application/json", headers=client.headers)


# -- progress ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_a_book_starts_with_no_progress(api, book):
    body = api.get(reverse("library:book-progress", args=[book.pk])).json()
    assert body["page"] == 0 and body["percentage"] == 0.0
    assert body["last_opened_at"] is None


@pytest.mark.django_db
def test_progress_is_recorded_and_read_back(api, book):
    response = put_progress(api, book, page=4, page_fraction=0.5)
    assert response.status_code == 200

    body = api.get(reverse("library:book-progress", args=[book.pk])).json()
    assert body["page"] == 4
    assert body["page_fraction"] == 0.5
    assert body["percentage"] == 45.0  # (4 + 0.5) / 10


@pytest.mark.django_db
def test_percentage_is_computed_by_the_server(api, book):
    """Two clients must not be able to disagree about it."""
    put_progress(api, book, page=9, page_fraction=1.0)
    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["percentage"] == 100.0


@pytest.mark.django_db
def test_a_page_past_the_end_is_clamped(api, book):
    put_progress(api, book, page=9999, page_fraction=0.0)
    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 9


@pytest.mark.django_db
def test_progress_survives_across_devices(api, book, user):
    put_progress(api, book, page=6, page_fraction=0.25)

    phone = Client()
    phone.force_login(user)
    body = phone.get(reverse("library:book-progress", args=[book.pk])).json()
    assert body["page"] == 6, "the other device did not resume where it left off"


@pytest.mark.django_db
def test_a_stale_write_does_not_rewind_a_reader(api, book):
    """The rule §19 and §21 leave undefined.

    A device backgrounded mid-book can flush its position long afterwards.
    Honouring that write would drag a reader who has since moved on back to
    where the other device was.
    """
    now = timezone.now()
    put_progress(api, book, page=8, page_fraction=0.0,
                 client_updated_at=now.isoformat())

    # The stale flush: recorded an hour earlier, arriving now.
    put_progress(api, book, page=1, page_fraction=0.0,
                 client_updated_at=(now - timedelta(hours=1)).isoformat())

    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 8


@pytest.mark.django_db
def test_a_newer_write_does_win(api, book):
    now = timezone.now()
    put_progress(api, book, page=2, page_fraction=0.0, client_updated_at=now.isoformat())
    put_progress(api, book, page=7, page_fraction=0.0,
                 client_updated_at=(now + timedelta(minutes=5)).isoformat())

    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 7


@pytest.mark.django_db
def test_writes_without_a_timestamp_fall_back_to_last_write_wins(api, book):
    put_progress(api, book, page=8, page_fraction=0.0)
    put_progress(api, book, page=3, page_fraction=0.0)
    assert api.get(reverse("library:book-progress", args=[book.pk])).json()["page"] == 3


@pytest.mark.django_db
def test_one_reader_cannot_see_or_move_anothers_progress(api, book, other_user):
    """PRD §19: sharing a book never shares where someone had got to."""
    put_progress(api, book, page=5, page_fraction=0.0)

    intruder = Client()
    intruder.force_login(other_user)
    assert intruder.get(reverse("library:book-progress", args=[book.pk])).status_code == 404

    assert ReadingProgress.objects.get(book=book).page == 5


@pytest.mark.django_db
def test_progress_appears_on_the_book_listing(api, book):
    put_progress(api, book, page=4, page_fraction=0.0)
    listed = api.get(reverse("library:books")).json()[0]
    assert listed["progress"]["percentage"] == 40.0


@pytest.mark.django_db
def test_listing_progress_does_not_grow_queries_per_book(api, book, user,
                                                         django_assert_max_num_queries):
    """A folder of 200 books must not become 200 extra progress queries."""
    from library.models import BookSource

    for index in range(15):
        created = Book.objects.create(owner=user, title=f"Book {index}")
        BookSource.objects.create(book=created, storage_key=f"{index:064d}",
                                  original_filename=f"{index}.pdf", file_size=10)
        ReadingProgress.objects.create(user=user, book=created, page=1, percentage=10)

    # Session, user, books, sources/folders, one prefetch — a small constant,
    # nowhere near one per book.
    with django_assert_max_num_queries(10):
        listed = api.get(reverse("library:books")).json()

    assert len(listed) == 16
    assert any(b["progress"] for b in listed)


# -- continue reading ------------------------------------------------------------ #

@pytest.mark.django_db
def test_continue_reading_lists_started_books(api, book):
    put_progress(api, book, page=3, page_fraction=0.0)
    body = api.get(reverse("library:continue-reading")).json()
    assert [b["id"] for b in body] == [book.pk]


@pytest.mark.django_db
def test_continue_reading_excludes_unstarted_and_finished(api, book):
    assert api.get(reverse("library:continue-reading")).json() == []

    put_progress(api, book, page=9, page_fraction=1.0)  # 100%
    assert api.get(reverse("library:continue-reading")).json() == []


@pytest.mark.django_db
def test_continue_reading_excludes_trashed_books(api, book):
    put_progress(api, book, page=3, page_fraction=0.0)
    book.trash()
    assert api.get(reverse("library:continue-reading")).json() == []


# -- outline ---------------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_pdf_without_an_outline_returns_an_empty_list(api, book):
    """Most scans have none; the sidebar simply has nothing to show."""
    response = api.get(reverse("library:book-outline", args=[book.pk]))
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.django_db
def test_the_outline_is_cached_between_requests(api, book, monkeypatch):
    from library import outline as outline_module

    calls = []
    original = outline_module._extract

    def counting(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(outline_module, "_extract", counting)
    api.get(reverse("library:book-outline", args=[book.pk]))
    api.get(reverse("library:book-outline", args=[book.pk]))
    assert len(calls) == 1


@pytest.mark.django_db
def test_outline_requires_ownership(api, book, other_user):
    intruder = Client()
    intruder.force_login(other_user)
    assert intruder.get(reverse("library:book-outline", args=[book.pk])).status_code == 404


@pytest.mark.django_db
def test_progress_is_kept_on_a_book_that_has_not_been_probed_yet(api):
    """A book opened before the ingest worker reaches it has no page count.

    Clamping against an unknown count collapsed every position to page 0, so a
    reader who opened a fresh upload lost their place.
    """
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Fresh.pdf", make_pdf(pages=12))]},
             headers=api.headers)
    fresh = Book.objects.get()
    assert fresh.page_count is None

    put_progress(api, fresh, page=7, page_fraction=0.0)

    assert api.get(reverse("library:book-progress", args=[fresh.pk])).json()["page"] == 7
