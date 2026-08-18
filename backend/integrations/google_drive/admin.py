from django.contrib import admin

from .models import DriveConnection, DriveRoot, SyncRun


class DriveRootInline(admin.TabularInline):
    model = DriveRoot
    extra = 0
    readonly_fields = ("last_synced_at", "created_at")


@admin.register(DriveConnection)
class DriveConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "provider_email", "status", "last_synced_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("user__email", "provider_email", "provider_account_id")
    list_select_related = ("user",)
    inlines = [DriveRootInline]

    # PRD §34: the refresh token must never be displayed in plaintext. Excluding
    # it from the form is what enforces that — a readonly field would still
    # render the decrypted value on the page.
    exclude = ("refresh_token",)
    readonly_fields = ("provider_account_id", "scopes_granted", "start_page_token",
                       "created_at", "updated_at", "token_state")

    @admin.display(description="Refresh token")
    def token_state(self, obj) -> str:
        if not obj.pk:
            return "—"
        return "stored (encrypted)" if obj.refresh_token else "absent"

    def has_add_permission(self, request) -> bool:
        # A connection only exists as the result of a real OAuth grant; one
        # typed in here would have no usable token.
        return False


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("id", "drive_connection", "status", "started_at", "finished_at",
                    "discovered", "added", "updated", "marked_missing", "failed")
    list_filter = ("status", "started_at")
    search_fields = ("drive_connection__user__email",)
    list_select_related = ("drive_connection", "drive_connection__user")
    readonly_fields = tuple(f.name for f in SyncRun._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False
