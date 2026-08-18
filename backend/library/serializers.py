from __future__ import annotations

from rest_framework import serializers

from .annotations import validate_position_data
from .models import (
    Book,
    Bookmark,
    BookSource,
    Folder,
    Highlight,
    PageNote,
    ReadingProgress,
    UploadBatch,
)


class FolderSerializer(serializers.ModelSerializer):
    path = serializers.CharField(read_only=True)
    has_children = serializers.SerializerMethodField()
    book_count = serializers.SerializerMethodField()
    folder_count = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = ("id", "name", "parent", "path", "has_children", "book_count",
                  "folder_count", "item_count", "deleted_at", "created_at", "updated_at")
        read_only_fields = ("id", "path", "has_children", "book_count", "folder_count",
                            "item_count", "deleted_at", "created_at", "updated_at")

    def get_has_children(self, obj) -> bool:
        return obj.children.filter(deleted_at__isnull=True).exists()

    def get_book_count(self, obj) -> int:
        return obj.books.filter(deleted_at__isnull=True).count()

    def get_folder_count(self, obj) -> int:
        return obj.children.filter(deleted_at__isnull=True).count()

    def get_item_count(self, obj) -> int:
        """Everything directly inside, folders included.

        A ZIP's outermost folder usually holds only subfolders, so counting
        books alone reported "0 items" for a folder full of books.
        """
        return self.get_folder_count(obj) + self.get_book_count(obj)

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("A folder needs a name.")
        if "/" in name or "\\" in name:
            raise serializers.ValidationError("A folder name cannot contain slashes.")
        return name[:255]

    def validate_parent(self, value):
        if value is None:
            return value
        request = self.context["request"]
        if value.owner_id != request.user.pk:
            # 'not found' rather than 'forbidden': confirming the folder exists
            # would leak another user's tree.
            raise serializers.ValidationError("No such folder.")
        if value.deleted_at is not None:
            raise serializers.ValidationError("That folder is in the trash.")
        return value


class BookSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookSource
        fields = ("original_filename", "content_type", "file_size", "availability_status",
                  "uploaded_at")
        read_only_fields = fields


class ReadingProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingProgress
        fields = ("page", "page_fraction", "percentage", "last_opened_at",
                  "updated_at", "client_updated_at")
        read_only_fields = ("percentage", "last_opened_at", "updated_at")


class ProgressWriteSerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=0)
    page_fraction = serializers.FloatField(min_value=0.0, max_value=1.0, default=0.0)
    # Optional. When present it is compared against the stored value to drop a
    # write that was recorded earlier than what the server already has.
    client_updated_at = serializers.DateTimeField(required=False, allow_null=True)


class SharedBookSerializer(serializers.ModelSerializer):
    """A book as someone who does not own it sees it.

    The original filename and the folder path describe the owner's own
    organisation, not the book, and a reader has no business seeing either.
    Kept as a separate class rather than a conditional inside BookSerializer,
    because a conditional is where that sort of leak hides (PRD §16, §29).
    """

    owner_name = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = ("id", "title", "page_count", "has_text_layer", "visibility",
                  "thumbnail_path", "owner_name", "progress", "created_at")
        read_only_fields = fields

    def get_owner_name(self, obj) -> str:
        return obj.owner.display_name or obj.owner.email.split("@")[0]

    def get_progress(self, obj):
        records = getattr(obj, "_reader_progress", None)
        if not records:
            return None
        record = records[0]
        return {"page": record.page, "page_fraction": record.page_fraction,
                "percentage": record.percentage, "last_opened_at": record.last_opened_at}


class BookSerializer(serializers.ModelSerializer):
    source = BookSourceSerializer(read_only=True)
    path = serializers.CharField(read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = ("id", "title", "folder", "path", "page_count", "has_text_layer",
                  "visibility", "thumbnail_path", "source", "progress", "deleted_at",
                  "created_at", "updated_at")
        read_only_fields = ("id", "path", "page_count", "has_text_layer", "thumbnail_path",
                            "source", "progress", "deleted_at", "created_at", "updated_at")

    def get_progress(self, obj):
        """Attached by the list view's prefetch; None when never opened."""
        records = getattr(obj, "_reader_progress", None)
        if not records:
            return None
        record = records[0]
        return {
            "page": record.page,
            "page_fraction": record.page_fraction,
            "percentage": record.percentage,
            "last_opened_at": record.last_opened_at,
        }

    def validate_title(self, value: str) -> str:
        title = value.strip()
        if not title:
            raise serializers.ValidationError("A book needs a title.")
        return title[:512]

    def validate_folder(self, value):
        if value is None:
            return value
        request = self.context["request"]
        if value.owner_id != request.user.pk or value.deleted_at is not None:
            raise serializers.ValidationError("No such folder.")
        return value


class UploadBatchSerializer(serializers.ModelSerializer):
    counts = serializers.DictField(read_only=True)

    class Meta:
        model = UploadBatch
        fields = ("id", "kind", "original_filename", "target_folder", "status", "counts",
                  "error_summary", "created_at", "started_at", "finished_at")
        read_only_fields = fields


class BookmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bookmark
        fields = ("id", "page", "page_fraction", "label", "created_at")
        read_only_fields = ("id", "created_at")


class HighlightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Highlight
        fields = ("id", "page", "selected_text", "position_data", "colour", "note",
                  "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_position_data(self, value):
        return validate_position_data(value)

    def validate_selected_text(self, value: str) -> str:
        # Generous, but bounded: this is the passage, not the book.
        return value[:5000]


class PageNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageNote
        fields = ("id", "page", "body", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_body(self, value: str) -> str:
        body = value.strip()
        if not body:
            raise serializers.ValidationError("A note needs some text.")
        return body[:20000]
