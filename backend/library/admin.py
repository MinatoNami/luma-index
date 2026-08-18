from django.contrib import admin

from .models import Book, BookSource


class BookSourceInline(admin.StackedInline):
    model = BookSource
    extra = 0
    readonly_fields = ("created_at", "updated_at", "last_seen_at")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "visibility", "page_count", "has_text_layer", "created_at")
    list_filter = ("visibility", "has_text_layer", "created_at")
    search_fields = ("title", "source__filename", "source__original_path", "owner__email")
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [BookSourceInline]


@admin.register(BookSource)
class BookSourceAdmin(admin.ModelAdmin):
    list_display = ("filename", "provider", "availability_status", "file_size", "last_seen_at")
    list_filter = ("provider", "availability_status")
    search_fields = ("filename", "original_path", "provider_file_id")
    readonly_fields = ("created_at", "updated_at", "cache_key")
