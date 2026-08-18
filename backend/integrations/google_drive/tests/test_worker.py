"""Sync worker scheduling and the sync endpoints."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from integrations.google_drive.management.commands.run_sync_worker import Command
from integrations.google_drive.models import DriveConnection, DriveRoot, SyncRun
from library.models import Book

from .fake_drive import FakeDrive

User = get_user_model()
PASSWORD = "a-long-enough-password-42"


@pytest.fixture
def user(db):
    return User.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def connection(user):
    return DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                          refresh_token="refresh-1")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    return client


def csrf(client) -> dict:
    return {"x-csrftoken": client.cookies["lumaindex_csrftoken"].value}


# -- scheduling ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_never_synced_connection_is_due(connection):
    assert connection in list(Command().due_connections(60))


@pytest.mark.django_db
def test_a_recently_synced_connection_is_not_due(connection):
    connection.last_synced_at = timezone.now()
    connection.save(update_fields=["last_synced_at"])
    assert connection not in list(Command().due_connections(60))


@pytest.mark.django_db
def test_a_stale_connection_is_due(connection):
    connection.last_synced_at = timezone.now() - timezone.timedelta(hours=3)
    connection.save(update_fields=["last_synced_at"])
    assert connection in list(Command().due_connections(60))


@pytest.mark.django_db
def test_a_user_request_makes_a_fresh_connection_due(connection):
    """'Sync now' must not wait for the scheduled interval."""
    connection.last_synced_at = timezone.now()
    connection.save(update_fields=["last_synced_at"])
    assert connection not in list(Command().due_connections(60))

    connection.request_sync()
    assert connection in list(Command().due_connections(60))


@pytest.mark.django_db
def test_expired_connections_are_not_retried(connection):
    """Retrying produces failed runs and Google calls until the user reconnects."""
    connection.last_synced_at = timezone.now() - timezone.timedelta(days=2)
    connection.mark_expired("invalid_grant")
    assert connection not in list(Command().due_connections(60))


@pytest.mark.django_db
def test_requested_syncs_are_served_before_scheduled_ones(user):
    DriveConnection.objects.create(user=user, provider_account_id="sub-a", refresh_token="r")
    requested = DriveConnection.objects.create(user=user, provider_account_id="sub-b",
                                               refresh_token="r")
    requested.request_sync()

    assert list(Command().due_connections(60))[0] == requested


# -- a full pass ----------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_a_single_pass_imports_a_library(connection, monkeypatch, tmp_path, settings):
    from integrations.google_drive import sync as sync_module
    from integrations.google_drive.client import DriveClient
    from library.tests.pdfs import make_pdf

    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.pdf("f1", "DDIA.pdf", "root", content=make_pdf(pages=2))
    DriveRoot.objects.create(drive_connection=connection, provider_folder_id="root",
                             name="Books")
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    settings.PDF_CACHE_DIR = tmp_path / "cache"

    monkeypatch.setattr(sync_module.oauth, "get_access_token", lambda *a, **k: "token")
    monkeypatch.setattr(
        sync_module, "DriveClient",
        lambda token, **kw: DriveClient(token, http=drive.client(), sleep=lambda _: None),
    )

    call_command("run_sync_worker", "--once")

    book = Book.objects.get(title="DDIA")
    assert book.page_count == 2
    assert book.thumbnail_path
    connection.refresh_from_db()
    assert connection.last_synced_at is not None
    assert connection.sync_requested_at is None, "the request flag should be cleared"
    assert SyncRun.objects.filter(drive_connection=connection,
                                  status=SyncRun.Status.OK).exists()


@pytest.mark.django_db(transaction=True)
def test_a_pass_survives_a_failing_connection(connection, user, monkeypatch):
    """One broken connection must not stop the worker for everyone else."""
    from integrations.google_drive import sync as sync_module

    def explode(*args, **kwargs):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(sync_module.oauth, "get_access_token", explode)
    call_command("run_sync_worker", "--once")  # must not raise


# -- endpoints ------------------------------------------------------------------- #

@pytest.mark.django_db
def test_requesting_a_sync_sets_the_flag(auth_client, connection):
    response = auth_client.post(reverse("drive:sync"), headers=csrf(auth_client))
    assert response.status_code == 202
    connection.refresh_from_db()
    assert connection.sync_requested_at is not None


@pytest.mark.django_db
def test_requesting_a_sync_without_a_connection_is_404(auth_client):
    assert auth_client.post(reverse("drive:sync"),
                            headers=csrf(auth_client)).status_code == 404


@pytest.mark.django_db
def test_requesting_a_sync_on_an_expired_connection_asks_to_reconnect(auth_client, connection):
    connection.mark_expired("invalid_grant")
    response = auth_client.post(reverse("drive:sync"), headers=csrf(auth_client))
    assert response.status_code == 409
    assert response.json()["code"] == "reauthorization_required"


@pytest.mark.django_db
def test_sync_history_is_listed(auth_client, connection):
    SyncRun.objects.create(drive_connection=connection, status=SyncRun.Status.OK,
                           discovered=3, added=3, finished_at=timezone.now())
    body = auth_client.get(reverse("drive:sync")).json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["counts"]["added"] == 3


@pytest.mark.django_db
def test_a_user_cannot_read_another_users_sync_run(auth_client, user):
    other = User.objects.create_user(email="mallory@example.com", password=PASSWORD)
    their_connection = DriveConnection.objects.create(user=other, provider_account_id="sub-2")
    run = SyncRun.objects.create(drive_connection=their_connection)

    assert auth_client.get(reverse("drive:sync-detail", args=[run.pk])).status_code == 404


@pytest.mark.django_db
def test_sync_endpoints_require_authentication():
    assert Client().post(reverse("drive:sync")).status_code == 403
    assert Client().get(reverse("drive:sync")).status_code == 403
