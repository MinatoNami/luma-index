"""Sync behaviour.

The tests that matter most are the ones asserting what sync does *not* do: a
walk that came back short must never mark files missing, and a lost
authorization must never cost a user their library.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from integrations.google_drive.client import DriveClient
from integrations.google_drive.models import DriveConnection, DriveRoot, SyncRun
from integrations.google_drive.sync import SyncBusy, process_pending_documents, sync_connection
from library.cache import PdfCache
from library.models import Book, BookSource

from ...google_drive.tests.fake_drive import FakeDrive

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="owner@example.com", password="a-long-password-42")


@pytest.fixture
def connection(user):
    return DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                          refresh_token="refresh-1")


@pytest.fixture
def drive() -> FakeDrive:
    fake = FakeDrive()
    fake.folder("root", "Books")
    fake.folder("prog", "Programming", "root")
    fake.pdf("f1", "DDIA.pdf", "prog")
    fake.pdf("f2", "Fluent Python.pdf", "prog")
    fake.pdf("f3", "Dune.pdf", "root")
    return fake


@pytest.fixture
def root(connection):
    return DriveRoot.objects.create(drive_connection=connection,
                                    provider_folder_id="root", name="Books")


def client_for(drive: FakeDrive) -> DriveClient:
    return DriveClient("access-token", http=drive.client(), sleep=lambda _: None)


# -- import ------------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_sync_imports_every_pdf(connection, root, drive):
    run = sync_connection(connection, client=client_for(drive))

    assert run.status == SyncRun.Status.OK
    assert run.added == 3
    assert set(Book.objects.values_list("title", flat=True)) == {
        "DDIA", "Fluent Python", "Dune"
    }


@pytest.mark.django_db(transaction=True)
def test_sync_preserves_the_drive_hierarchy(connection, root, drive):
    """PRD §10: the original path is kept."""
    sync_connection(connection, client=client_for(drive))
    paths = set(BookSource.objects.values_list("original_path", flat=True))
    assert "Books/Programming/DDIA.pdf" in paths
    assert "Books/Dune.pdf" in paths


@pytest.mark.django_db(transaction=True)
def test_sync_is_idempotent(connection, root, drive):
    sync_connection(connection, client=client_for(drive))
    second = sync_connection(connection, client=client_for(drive))

    assert second.added == 0
    assert Book.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_a_renamed_file_updates_rather_than_duplicates(connection, root, drive):
    """PRD §13: identity is the file ID, never the name or path."""
    sync_connection(connection, client=client_for(drive))
    drive.files["f1"].name = "Designing Data-Intensive Applications.pdf"

    run = sync_connection(connection, client=client_for(drive))

    assert run.added == 0
    assert run.updated == 1
    assert Book.objects.count() == 3
    assert BookSource.objects.get(provider_file_id="f1").filename == (
        "Designing Data-Intensive Applications.pdf"
    )


@pytest.mark.django_db(transaction=True)
def test_a_moved_file_updates_its_path(connection, root, drive):
    sync_connection(connection, client=client_for(drive))
    drive.files["f1"].parents = ["root"]

    sync_connection(connection, client=client_for(drive))

    assert BookSource.objects.get(provider_file_id="f1").original_path == "Books/DDIA.pdf"
    assert Book.objects.count() == 3


# -- the missing-file rule ----------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_a_deleted_file_is_marked_missing_not_deleted(connection, root, drive):
    """PRD §13: the book, its progress, and its annotations must survive."""
    sync_connection(connection, client=client_for(drive))
    book = Book.objects.get(title="Dune")

    del drive.files["f3"]
    run = sync_connection(connection, client=client_for(drive))

    assert run.marked_missing == 1
    assert Book.objects.filter(pk=book.pk).exists()
    source = BookSource.objects.get(provider_file_id="f3")
    assert source.availability_status == BookSource.Availability.MISSING


@pytest.mark.django_db(transaction=True)
def test_an_unreadable_subfolder_does_not_mark_anything_missing(connection, root, drive):
    """The central safety rule: a short listing is not a deletion."""
    sync_connection(connection, client=client_for(drive))
    assert BookSource.objects.filter(
        availability_status=BookSource.Availability.AVAILABLE).count() == 3

    drive.forbidden_folders.add("prog")   # two books now invisible
    run = sync_connection(connection, client=client_for(drive))

    assert run.status == SyncRun.Status.PARTIAL
    assert run.marked_missing == 0, "an incomplete walk must not mark anything missing"
    assert BookSource.objects.filter(
        availability_status=BookSource.Availability.AVAILABLE).count() == 3
    assert run.error_summary


@pytest.mark.django_db(transaction=True)
def test_a_drive_outage_does_not_mark_anything_missing(connection, root, drive):
    sync_connection(connection, client=client_for(drive))

    drive.failures = [503] * 40
    run = sync_connection(connection, client=client_for(drive))

    assert run.marked_missing == 0
    assert BookSource.objects.filter(
        availability_status=BookSource.Availability.AVAILABLE).count() == 3


@pytest.mark.django_db(transaction=True)
def test_a_reappearing_file_becomes_available_again(connection, root, drive):
    sync_connection(connection, client=client_for(drive))
    removed = drive.files.pop("f3")
    sync_connection(connection, client=client_for(drive))
    assert BookSource.objects.get(provider_file_id="f3").availability_status == (
        BookSource.Availability.MISSING
    )

    drive.files["f3"] = removed
    sync_connection(connection, client=client_for(drive))

    assert BookSource.objects.get(provider_file_id="f3").availability_status == (
        BookSource.Availability.AVAILABLE
    )


# -- authorization ------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_lost_authorization_fails_the_run_without_touching_data(connection, root, drive):
    sync_connection(connection, client=client_for(drive))

    drive.failures = [401] * 40
    run = sync_connection(connection, client=client_for(drive))

    assert run.status in {SyncRun.Status.PARTIAL, SyncRun.Status.FAILED}
    assert run.marked_missing == 0
    assert Book.objects.count() == 3


# -- concurrency ---------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_a_second_sync_for_one_connection_is_refused(connection, root, drive):
    """Two concurrent syncs would duplicate work and race each other.

    The lock must be held on a *different* database session: PostgreSQL
    advisory locks are re-entrant within one session, and the real contenders
    are separate processes (a gunicorn worker and the sync worker).
    """
    import threading

    from common.db import advisory_lock
    from integrations.google_drive.sync import connection_lock_key

    holding = threading.Event()
    release = threading.Event()

    def hold():
        from django.db import connection as db
        with advisory_lock(connection_lock_key(connection.pk)):
            holding.set()
            release.wait(timeout=10)
        db.close()

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(timeout=10)
        with pytest.raises(SyncBusy):
            sync_connection(connection, client=client_for(drive))
    finally:
        release.set()
        thread.join(timeout=10)


# -- content processing ---------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_processing_probes_and_thumbnails(connection, root, drive, tmp_path, settings):
    from library.tests.pdfs import make_pdf

    for file_id in ("f1", "f2", "f3"):
        drive.files[file_id].content = make_pdf(pages=3)

    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    sync_connection(connection, client=client_for(drive))

    result = process_pending_documents(
        connection, client=client_for(drive),
        cache=PdfCache(root=tmp_path / "cache", max_bytes=10_000_000),
    )

    assert result["processed"] == 3
    assert result["remaining"] == 0
    for book in Book.objects.all():
        assert book.page_count == 3
        assert book.has_text_layer is True
        assert (tmp_path / "thumbs" / book.thumbnail_path).exists()


@pytest.mark.django_db(transaction=True)
def test_a_corrupt_pdf_does_not_stop_the_batch(connection, root, drive, tmp_path, settings):
    from library.tests.pdfs import make_pdf

    drive.files["f1"].content = b"%PDF-1.4 truncated garbage"
    drive.files["f2"].content = make_pdf(pages=2)
    drive.files["f3"].content = make_pdf(pages=2)

    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    sync_connection(connection, client=client_for(drive))

    result = process_pending_documents(
        connection, client=client_for(drive),
        cache=PdfCache(root=tmp_path / "cache", max_bytes=10_000_000),
    )

    assert result["processed"] == 2
    assert result["failed"] == 1
    assert BookSource.objects.get(provider_file_id="f1").availability_status == (
        BookSource.Availability.ERROR
    )


@pytest.mark.django_db(transaction=True)
def test_processing_is_batched(connection, root, drive, tmp_path, settings):
    from library.tests.pdfs import make_pdf

    for file_id in ("f1", "f2", "f3"):
        drive.files[file_id].content = make_pdf(pages=1)
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    sync_connection(connection, client=client_for(drive))

    result = process_pending_documents(
        connection, limit=2, client=client_for(drive),
        cache=PdfCache(root=tmp_path / "cache", max_bytes=10_000_000),
    )

    assert result["processed"] == 2
    assert result["remaining"] == 1


@pytest.mark.django_db(transaction=True)
def test_changed_content_invalidates_derived_data_but_not_the_book(
    connection, root, drive, tmp_path, settings
):
    """A new revision re-probes; reading state belongs to the Book, not the file."""
    from library.tests.pdfs import make_pdf

    for file_id in ("f1", "f2", "f3"):
        drive.files[file_id].content = make_pdf(pages=1)
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    cache = PdfCache(root=tmp_path / "cache", max_bytes=10_000_000)

    sync_connection(connection, client=client_for(drive))
    process_pending_documents(connection, client=client_for(drive), cache=cache)
    book = Book.objects.get(title="DDIA")
    assert book.page_count == 1

    drive.files["f1"].content = make_pdf(pages=5)
    drive.files["f1"].modified = "2026-06-01T00:00:00.000Z"
    sync_connection(connection, client=client_for(drive))

    book.refresh_from_db()
    assert book.page_count is None, "stale page count survived a content change"
    assert Book.objects.filter(pk=book.pk).exists()

    process_pending_documents(connection, client=client_for(drive), cache=cache)
    book.refresh_from_db()
    assert book.page_count == 5
