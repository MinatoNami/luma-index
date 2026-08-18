"""Google Drive connections, selected roots, and sync history."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from common.encryption import EncryptedTextField


class DriveConnection(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        # Google's OAuth consent screen expires refresh tokens after 7 days
        # while the app is in Testing mode, so this is an ordinary state to be
        # in — not an error. See docs/google-oauth.md.
        EXPIRED = "expired", "Authorization expired"
        REVOKED = "revoked", "Revoked by user"
        ERROR = "error", "Error"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="drive_connections"
    )

    # Google's 'sub' claim. Stable across email changes, unlike the address.
    provider_account_id = models.CharField(max_length=255)
    provider_email = models.EmailField(blank=True)

    refresh_token = EncryptedTextField(blank=True)

    # What the user actually consented to, which can be less than what was
    # requested. Checking this beats assuming the request succeeded.
    scopes_granted = models.TextField(blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # Operator-facing reason. Never a token — see common.logging.
    status_detail = models.CharField(max_length=512, blank=True)

    # Stored from day one even though incremental sync is a later phase: it
    # costs nothing now and cannot be back-filled for the past.
    start_page_token = models.CharField(max_length=255, blank=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_requested_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider_account_id"], name="unique_drive_account_per_user"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.provider_email or self.provider_account_id}"

    @property
    def needs_reauthorization(self) -> bool:
        return self.status in {self.Status.EXPIRED, self.Status.REVOKED}

    def mark_expired(self, detail: str = "") -> None:
        """Record that the token stopped working.

        Deliberately touches nothing but this row. PRD §13 and §35 require that
        losing authorization never destroys books, progress, or annotations.
        """
        self.status = self.Status.EXPIRED
        self.status_detail = detail[:512]
        self.save(update_fields=["status", "status_detail", "updated_at"])

    def request_sync(self) -> None:
        self.sync_requested_at = timezone.now()
        self.save(update_fields=["sync_requested_at", "updated_at"])


class DriveRoot(models.Model):
    """A folder the user chose to import from."""

    drive_connection = models.ForeignKey(
        DriveConnection, on_delete=models.CASCADE, related_name="roots"
    )
    provider_folder_id = models.CharField(max_length=255)
    name = models.CharField(max_length=512)
    original_path = models.CharField(max_length=2048, blank=True)
    sync_enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["drive_connection", "provider_folder_id"], name="unique_root_per_connection"
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SyncRun(models.Model):
    """One synchronization attempt.

    PRD §8 gives admins the ability to "inspect sync failures", which needs
    somewhere for a failure to be recorded. Also what the UI polls for progress.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        OK = "ok", "Completed"
        PARTIAL = "partial", "Completed with errors"
        FAILED = "failed", "Failed"

    drive_connection = models.ForeignKey(
        DriveConnection, on_delete=models.CASCADE, related_name="sync_runs"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    discovered = models.PositiveIntegerField(default=0)
    added = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    marked_missing = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)

    error_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["drive_connection", "-started_at"])]

    def __str__(self) -> str:
        return f"sync {self.pk} ({self.status})"

    @property
    def counts(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "added": self.added,
            "updated": self.updated,
            "marked_missing": self.marked_missing,
            "failed": self.failed,
        }
