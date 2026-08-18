"""Model-level guarantees.

These encode the on_delete decisions from docs/phases/06-sharing.md. Getting
one of them backwards silently destroys user data, and the failure only shows
up long after the change that caused it.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from integrations.google_drive.models import DriveConnection
from library.models import Book, BookSource

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password="a-long-password-42")


@pytest.fixture
def connection(owner):
    return DriveConnection.objects.create(user=owner, provider_account_id="google-sub-1",
                                          provider_email="owner@gmail.com")


@pytest.fixture
def book(owner, connection):
    book = Book.objects.create(owner=owner, title="Designing Data-Intensive Applications")
    BookSource.objects.create(
        book=book, drive_connection=connection, provider_file_id="drive-file-1",
        filename="DDIA.pdf", original_path="Books/Programming/DDIA.pdf",
        provider_modified_at=timezone.now(),
    )
    return book


@pytest.mark.django_db
def test_books_are_private_by_default(owner):
    """PRD §16. The default lives on the model so no code path can miss it."""
    assert Book.objects.create(owner=owner, title="x").visibility == Book.Visibility.PRIVATE


@pytest.mark.django_db
def test_one_drive_file_cannot_become_two_sources(book, connection, owner):
    other = Book.objects.create(owner=owner, title="duplicate")
    with pytest.raises(IntegrityError):
        BookSource.objects.create(book=other, drive_connection=connection,
                                  provider_file_id="drive-file-1", filename="DDIA.pdf")


@pytest.mark.django_db
def test_disconnecting_drive_keeps_the_library(book, connection):
    """PRD §33: a disconnect must not destroy books or, by extension, annotations."""
    connection.delete()

    book.refresh_from_db()
    source = BookSource.objects.get(book=book)
    assert source.drive_connection is None
    assert source.filename == "DDIA.pdf"
    assert Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_deleting_a_book_removes_its_source(book):
    book.delete()
    assert not BookSource.objects.filter(provider_file_id="drive-file-1").exists()


@pytest.mark.django_db
def test_deleting_a_user_removes_their_books(owner, book):
    owner.delete()
    assert not Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_cache_key_changes_when_the_file_changes(book):
    """PRD §25: a modified file must not keep serving previously cached bytes."""
    source = book.source
    before = source.cache_key

    source.provider_modified_at = timezone.now() + timezone.timedelta(hours=1)
    source.save(update_fields=["provider_modified_at"])
    assert source.cache_key != before

    source.provider_checksum = "abc123"
    source.save(update_fields=["provider_checksum"])
    checksum_key = source.cache_key

    # A checksum is a stronger identity than a timestamp, so it wins.
    source.provider_modified_at = timezone.now() + timezone.timedelta(hours=2)
    source.save(update_fields=["provider_modified_at"])
    assert source.cache_key == checksum_key


@pytest.mark.django_db
def test_cache_key_is_not_derived_from_the_filename(book):
    """PRD §13: a rename must not look like a different file."""
    source = book.source
    before = source.cache_key
    source.filename = "Designing Data-Intensive Applications.pdf"
    source.original_path = "Books/Architecture/DDIA.pdf"
    source.save(update_fields=["filename", "original_path"])
    assert source.cache_key == before
