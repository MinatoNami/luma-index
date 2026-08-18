from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from integrations.google_drive.models import DriveConnection, DriveRoot, SyncRun
from library.models import Book, BookSource

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="reader@example.com", password="a-long-password-42")


@pytest.fixture
def connection(user):
    return DriveConnection.objects.create(user=user, provider_account_id="sub-1")


@pytest.mark.django_db
def test_refresh_token_is_encrypted_in_the_database(connection):
    """Reads the raw column: round-tripping through the ORM proves nothing."""
    connection.refresh_token = "1//0g-super-secret-refresh-token"
    connection.save(update_fields=["refresh_token"])

    from django.db import connection as db

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT refresh_token FROM google_drive_driveconnection WHERE id = %s",
            [connection.pk],
        )
        stored = cursor.fetchone()[0]

    assert "1//0g-super-secret-refresh-token" not in stored
    assert stored.startswith("gAAAAA")  # Fernet
    assert DriveConnection.objects.get(pk=connection.pk).refresh_token == (
        "1//0g-super-secret-refresh-token"
    )


@pytest.mark.django_db
def test_one_google_account_links_once_per_user(connection, user):
    with pytest.raises(IntegrityError):
        DriveConnection.objects.create(user=user, provider_account_id="sub-1")


@pytest.mark.django_db
def test_expiring_a_connection_preserves_the_library(connection, user):
    """The 7-day Testing-mode expiry happens routinely; it must be harmless."""
    book = Book.objects.create(owner=user, title="Dune")
    BookSource.objects.create(book=book, drive_connection=connection,
                              provider_file_id="f1", filename="Dune.pdf")

    connection.mark_expired("invalid_grant")

    connection.refresh_from_db()
    assert connection.status == DriveConnection.Status.EXPIRED
    assert connection.needs_reauthorization
    assert Book.objects.filter(pk=book.pk).exists()
    assert BookSource.objects.filter(book=book).exists()


@pytest.mark.django_db
def test_roots_are_unique_per_connection(connection):
    DriveRoot.objects.create(drive_connection=connection, provider_folder_id="folder-1",
                             name="Books")
    with pytest.raises(IntegrityError):
        DriveRoot.objects.create(drive_connection=connection, provider_folder_id="folder-1",
                                 name="Books again")


@pytest.mark.django_db
def test_sync_run_reports_counts(connection):
    run = SyncRun.objects.create(drive_connection=connection, discovered=10, added=7,
                                 updated=2, failed=1, status=SyncRun.Status.PARTIAL,
                                 finished_at=timezone.now())
    assert run.counts == {"discovered": 10, "added": 7, "updated": 2,
                          "marked_missing": 0, "failed": 1}
