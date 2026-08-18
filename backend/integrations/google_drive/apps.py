from django.apps import AppConfig


class GoogleDriveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.google_drive"
    # Without an explicit label Django would derive "google_drive" anyway, but
    # pinning it keeps migration and FK references stable if the module moves.
    label = "google_drive"
