"""Books and their storage sources.

PRD §14 separates the logical book from where its bytes live, so a second
storage provider can be added without touching the reader or the library:

    Book  ->  BookSource  ->  Google Drive
                          ->  (later) local upload, Dropbox, OneDrive
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Book(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        SHARED = "shared", "Shared with instance"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books"
    )
    title = models.CharField(max_length=512)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    # None = not probed yet. False drives the PRD §27 "search unavailable"
    # message rather than letting a search silently return nothing.
    has_text_layer = models.BooleanField(null=True, blank=True)

    # PRD §16: private by default. The default lives here rather than in a
    # serializer so no code path can create a book that is shared by accident.
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE
    )

    thumbnail_path = models.CharField(max_length=512, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["visibility"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_shared(self) -> bool:
        return self.visibility == self.Visibility.SHARED


class BookSource(models.Model):
    class Provider(models.TextChoices):
        GOOGLE_DRIVE = "google_drive", "Google Drive"

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available"
        MISSING = "missing", "Missing from provider"
        FORBIDDEN = "forbidden", "Access denied"
        ERROR = "error", "Error"

    book = models.OneToOneField(Book, on_delete=models.CASCADE, related_name="source")

    # SET_NULL, deliberately. Disconnecting Drive must not delete the library:
    # PRD §33 requires annotations to survive a disconnect, and cascading here
    # would take the books out from under them.
    drive_connection = models.ForeignKey(
        "google_drive.DriveConnection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources",
    )

    provider = models.CharField(
        max_length=32, choices=Provider.choices, default=Provider.GOOGLE_DRIVE
    )

    # The immutable identity. PRD §13 requires renames and moves to update a
    # record rather than create a duplicate, which only works if nothing keys
    # on the name or the path.
    provider_file_id = models.CharField(max_length=255)
    provider_parent_id = models.CharField(max_length=255, blank=True)

    original_path = models.CharField(max_length=2048, blank=True)
    filename = models.CharField(max_length=512)
    mime_type = models.CharField(max_length=128, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    provider_modified_at = models.DateTimeField(null=True, blank=True)

    # Part of the cache key: a file whose content changed must not keep serving
    # the previously cached bytes (PRD §25).
    provider_checksum = models.CharField(max_length=128, blank=True)

    availability_status = models.CharField(
        max_length=16, choices=Availability.choices, default=Availability.AVAILABLE
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_file_id"],
                name="unique_source_per_provider_file",
            )
        ]
        indexes = [models.Index(fields=["availability_status"])]

    def __str__(self) -> str:
        return f"{self.filename} ({self.provider})"

    @property
    def is_available(self) -> bool:
        return self.availability_status == self.Availability.AVAILABLE

    @property
    def cache_key(self) -> str:
        """Identity of the exact bytes, not just the file.

        Includes the version so a modified file invalidates itself instead of
        serving stale content forever. PRD §25 says never trust filenames; a
        file ID alone is not enough either.
        """
        import hashlib

        version = self.provider_checksum or (
            self.provider_modified_at.isoformat() if self.provider_modified_at else "0"
        )
        raw = f"{self.provider}:{self.provider_file_id}:{version}"
        return hashlib.sha256(raw.encode()).hexdigest()
