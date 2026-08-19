"""The trash emptying itself.

This is the only code that destroys a file nobody asked it to destroy, so what
these pin down is mostly what it refuses to touch.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from library.models import Book, BookSource, Folder
from library.retention import cutoff, expires_at, purge_expired, retention_days
from library.storage import LibraryStorage


def ago(days):
    return timezone.now() - timedelta(days=days)


def trashed_book(user, title, *, days, folder=None, key=None, storage=None):
    book = Book.objects.create(owner=user, title=title, folder=folder, deleted_at=ago(days))
    key = key or (f"{abs(hash(title)):064x}"[:64])
    BookSource.objects.create(book=book, storage_key=key, original_filename=f"{title}.pdf",
                              file_size=10)
    if storage is not None:
        path = storage.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 stub")
    return book


# -- off by default ------------------------------------------------------------- #

@pytest.mark.django_db
def test_nothing_is_swept_unless_retention_is_turned_on(user, settings):
    """The PDF in the trash may be its owner's only copy, and deleting it is
    meant to be two explicit steps."""
    settings.TRASH_RETENTION_DAYS = 0
    trashed_book(user, "Ancient", days=4000)

    assert retention_days() == 0
    assert cutoff() is None
    assert purge_expired() == {"folders": 0, "books": 0, "files": 0, "skipped": 0}
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_expires_at_is_none_when_retention_is_off(settings):
    settings.TRASH_RETENTION_DAYS = 0

    assert expires_at(ago(1)) is None


@pytest.mark.django_db
def test_expires_at_counts_from_when_it_was_trashed(settings):
    settings.TRASH_RETENTION_DAYS = 30
    when = ago(10)

    assert expires_at(when) == when + timedelta(days=30)


# -- what goes and what stays ---------------------------------------------------- #

@pytest.mark.django_db
def test_a_book_past_its_retention_is_destroyed(user, settings):
    settings.TRASH_RETENTION_DAYS = 30
    trashed_book(user, "Old", days=31)

    result = purge_expired()

    assert result["books"] == 1
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_a_book_still_inside_its_retention_is_left_alone(user, settings):
    settings.TRASH_RETENTION_DAYS = 30
    trashed_book(user, "Recent", days=29)

    assert purge_expired()["books"] == 0
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_a_live_book_is_never_touched(user, settings):
    """Age is measured from the trash, not from creation — a book you have had
    for years and never deleted is not old, it is yours."""
    settings.TRASH_RETENTION_DAYS = 1
    old = Book.objects.create(owner=user, title="Kept")
    Book.objects.filter(pk=old.pk).update(created_at=ago(4000))

    assert purge_expired()["books"] == 0
    assert Book.objects.filter(pk=old.pk).exists()


@pytest.mark.django_db
def test_a_trashed_folder_takes_its_contents_with_it(user, settings):
    settings.TRASH_RETENTION_DAYS = 30
    folder = Folder.objects.create(owner=user, name="Old", deleted_at=ago(40))
    inner = Folder.objects.create(owner=user, name="Inner", parent=folder, deleted_at=ago(40))
    trashed_book(user, "Inside", days=40, folder=inner)

    result = purge_expired()

    assert result["folders"] == 2
    assert Folder.objects.count() == 0
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_a_folder_holding_a_live_book_is_refused(user, settings):
    """Should be impossible — trashing a folder trashes its contents, and
    nothing can be moved into the trash afterwards. A cascade delete does not
    check, though, and the cost of being wrong is somebody's only copy."""
    settings.TRASH_RETENTION_DAYS = 30
    folder = Folder.objects.create(owner=user, name="Odd", deleted_at=ago(40))
    survivor = Book.objects.create(owner=user, title="Still mine", folder=folder)

    result = purge_expired()

    assert result["skipped"] == 1
    assert result["folders"] == 0
    assert Book.objects.filter(pk=survivor.pk).exists()
    assert Folder.objects.filter(pk=folder.pk).exists()


@pytest.mark.django_db
def test_a_folder_trashed_recently_survives_even_if_a_book_in_it_is_old(user, settings):
    """The book was deleted separately and earlier; it goes, the folder stays."""
    settings.TRASH_RETENTION_DAYS = 30
    folder = Folder.objects.create(owner=user, name="Newer", deleted_at=ago(2))
    trashed_book(user, "Older", days=90, folder=folder)

    result = purge_expired()

    assert (result["books"], result["folders"]) == (1, 0)
    assert Folder.objects.filter(pk=folder.pk).exists()


# -- the files behind the rows ---------------------------------------------------- #

@pytest.mark.django_db
def test_the_file_on_disk_goes_too(user, settings, isolated_storage):
    settings.TRASH_RETENTION_DAYS = 30
    storage = LibraryStorage()
    key = "a" * 64
    trashed_book(user, "Old", days=40, key=key, storage=storage)
    assert storage.exists(key)

    result = purge_expired()

    assert result["files"] == 1
    assert not storage.exists(key)


@pytest.mark.django_db
def test_a_file_another_book_still_points_at_is_kept(user, settings, isolated_storage):
    """Content addressing means two books can share one blob, and the other may
    not be trashed at all."""
    settings.TRASH_RETENTION_DAYS = 30
    storage = LibraryStorage()
    key = "b" * 64
    trashed_book(user, "Old copy", days=40, key=key, storage=storage)

    keeper = Book.objects.create(owner=user, title="Live copy")
    BookSource.objects.create(book=keeper, storage_key=key, original_filename="k.pdf",
                              file_size=10)

    result = purge_expired()

    assert result["books"] == 1
    assert result["files"] == 0
    assert storage.exists(key), "the live book still needs those bytes"


# -- bounded work ----------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_sweep_is_bounded_and_takes_the_oldest_first(user, settings):
    """One enormous trash must not hold the worker for minutes; the rest goes on
    the next pass."""
    settings.TRASH_RETENTION_DAYS = 30
    for n in range(6):
        trashed_book(user, f"Book {n}", days=100 - n, key=f"{n:064d}")

    first = purge_expired(limit=2)

    assert first["books"] == 2
    assert Book.objects.count() == 4
    assert set(Book.objects.values_list("title", flat=True)) == {
        "Book 2", "Book 3", "Book 4", "Book 5"}, "the two oldest went"


# -- the command ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_the_command_deletes_nothing_when_asked_to_dry_run(user, settings, capsys):
    settings.TRASH_RETENTION_DAYS = 30
    trashed_book(user, "Old", days=40)

    call_command("empty_trash", "--dry-run")

    assert "Would delete" in capsys.readouterr().out
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_the_command_says_so_when_retention_is_off(user, settings, capsys):
    settings.TRASH_RETENTION_DAYS = 0
    trashed_book(user, "Old", days=4000)

    call_command("empty_trash")

    assert "retention is off" in capsys.readouterr().out
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_the_command_can_override_the_period_for_one_run(user, settings, capsys):
    settings.TRASH_RETENTION_DAYS = 0
    trashed_book(user, "Old", days=40)

    call_command("empty_trash", "--days", "30")

    assert Book.objects.count() == 0
    assert "Deleted" in capsys.readouterr().out


# -- the worker ------------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_the_worker_sweeps_on_its_first_pass(user, settings):
    """The clock starts at zero rather than "now", so a worker that has just
    restarted sweeps immediately — after a restart the trash is the thing most
    likely to be overdue."""
    settings.TRASH_RETENTION_DAYS = 30
    trashed_book(user, "Old", days=40)

    call_command("run_ingest_worker", "--once")

    assert Book.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_worker_sweeps_on_a_machine_that_just_booted(user, settings, monkeypatch):
    """time.monotonic() counts from boot on Linux, so on a host up for less
    than the sweep interval the elapsed-time check used to compare against zero
    and conclude it had just swept. CI runners are always in that state; the
    real cost is a rebooted server ignoring its trash for an hour."""
    settings.TRASH_RETENTION_DAYS = 30
    trashed_book(user, "Old", days=40)
    monkeypatch.setattr("library.management.commands.run_ingest_worker.time.monotonic",
                        lambda: 5.0)

    call_command("run_ingest_worker", "--once")

    assert Book.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_worker_leaves_the_trash_alone_when_retention_is_off(user, settings):
    settings.TRASH_RETENTION_DAYS = 0
    trashed_book(user, "Old", days=4000)

    call_command("run_ingest_worker", "--once")

    assert Book.objects.count() == 1
