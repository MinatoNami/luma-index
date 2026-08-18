from django.contrib import admin

from .models import Book, BookSource, Folder, UploadBatch


class BookSourceInline(admin.StackedInline):
    model = BookSource
    extra = 0
    readonly_fields = ("storage_key", "original_filename", "content_type", "file_size",
                       "uploaded_at", "updated_at")


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "path", "deleted_at", "created_at")
    list_filter = ("deleted_at", "created_at")
    search_fields = ("name", "owner__email")
    list_select_related = ("owner", "parent")
    readonly_fields = ("path", "created_at", "updated_at")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "folder", "visibility", "page_count",
                    "has_text_layer", "deleted_at")
    list_filter = ("visibility", "has_text_layer", "deleted_at")
    search_fields = ("title", "source__original_filename", "owner__email")
    list_select_related = ("owner", "folder")
    readonly_fields = ("path", "created_at", "updated_at")
    inlines = [BookSourceInline]


@admin.register(BookSource)
class BookSourceAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "provider", "availability_status", "file_size",
                    "uploaded_at")
    list_filter = ("provider", "availability_status")
    search_fields = ("original_filename", "storage_key")
    readonly_fields = ("storage_key", "uploaded_at", "updated_at")


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "owner", "status", "discovered", "imported",
                    "skipped_duplicate", "failed", "created_at")
    list_filter = ("status", "kind", "created_at")
    search_fields = ("original_filename", "owner__email")
    list_select_related = ("owner",)
    readonly_fields = tuple(f.name for f in UploadBatch._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False
