from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .annotations import validate_position_data
from .models import (
    Book,
    Bookmark,
    BookSource,
    Collection,
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


class ProgressSummarySerializer(serializers.Serializer):
    """The shape embedded in a book listing.

    Declared so the published OpenAPI schema describes it, rather than
    defaulting an untyped SerializerMethodField to "string" — which makes the
    schema wrong for every client generated from it (PRD §31).
    """

    page = serializers.IntegerField()
    page_fraction = serializers.FloatField()
    percentage = serializers.FloatField()
    last_opened_at = serializers.DateTimeField(allow_null=True)


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

    @extend_schema_field(serializers.CharField())
    def get_owner_name(self, obj) -> str:
        return obj.owner.display_name or obj.owner.email.split("@")[0]

    @extend_schema_field(ProgressSummarySerializer(allow_null=True))
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
    is_favourite = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = ("id", "title", "folder", "path", "page_count", "has_text_layer",
                  "visibility", "thumbnail_path", "source", "progress", "is_favourite",
                  "deleted_at", "created_at", "updated_at")
        read_only_fields = ("id", "path", "page_count", "has_text_layer", "thumbnail_path",
                            "source", "progress", "is_favourite", "deleted_at",
                            "created_at", "updated_at")

    @extend_schema_field(serializers.BooleanField())
    def get_is_favourite(self, obj) -> bool:
        """Attached by the list view's prefetch, so this costs no extra query."""
        states = getattr(obj, "_reader_state", None)
        return bool(states and states[0].is_favourite)

    @extend_schema_field(ProgressSummarySerializer(allow_null=True))
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


class UploadRequestSerializer(serializers.Serializer):
    """Multipart upload body, for the schema."""

    files = serializers.ListField(
        child=serializers.FileField(),
        help_text="One or more PDFs, or a ZIP archive of them.",
    )
    folder = serializers.IntegerField(required=False, help_text="Target folder; root if omitted.")


class CollectionSerializer(serializers.ModelSerializer):
    path = serializers.CharField(read_only=True)
    book_count = serializers.SerializerMethodField()
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = ("id", "name", "parent", "path", "book_count", "has_children",
                  "created_at", "updated_at")
        read_only_fields = ("id", "path", "book_count", "has_children",
                            "created_at", "updated_at")

    @extend_schema_field(serializers.IntegerField())
    def get_book_count(self, obj) -> int:
        return obj.memberships.filter(book__deleted_at__isnull=True).count()

    @extend_schema_field(serializers.BooleanField())
    def get_has_children(self, obj) -> bool:
        return obj.children.exists()

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("A collection needs a name.")
        return name[:255]

    def validate_parent(self, value):
        if value is None:
            return value
        if value.owner_id != self.context["request"].user.pk:
            # "No such collection" rather than "forbidden": confirming it exists
            # would leak another user's structure.
            raise serializers.ValidationError("No such collection.")
        return value
