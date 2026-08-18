"""Per-user preferences.

PRD §24 wants these to follow a user between devices, which is the whole point
of storing them here rather than in localStorage: a reader who sets dark mode
on a tablet should not meet a white screen on their laptop.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class UserSettings(models.Model):
    class Theme(models.TextChoices):
        SYSTEM = "system", "Follow system"
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    class LibraryView(models.TextChoices):
        LIST = "list", "List"
        GRID = "grid", "Grid"
        LARGE = "large", "Large icons"

    class ReaderMode(models.TextChoices):
        CONTINUOUS = "continuous", "Continuous scroll"
        SINGLE = "single", "Single page"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="settings"
    )

    theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.SYSTEM)
    library_view = models.CharField(
        max_length=16, choices=LibraryView.choices, default=LibraryView.LIST
    )

    # Read by the reader when it lands (PRD §20, §24). Stored now so the
    # settings page and its migration do not need revisiting then.
    reader_mode = models.CharField(
        max_length=16, choices=ReaderMode.choices, default=ReaderMode.CONTINUOUS
    )
    reader_zoom = models.CharField(max_length=16, default="fit-width")
    sidebar_open = models.BooleanField(default=True)

    # Anything not yet worth a column of its own.
    preferences = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user settings"
        verbose_name_plural = "user settings"

    def __str__(self) -> str:
        return f"settings for {self.user}"

    @classmethod
    def for_user(cls, user) -> UserSettings:
        """Fetch or create. Done on read rather than by a signal on user
        creation, so a user made before this model existed still works."""
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
