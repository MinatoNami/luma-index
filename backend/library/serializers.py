from __future__ import annotations

from rest_framework import serializers

from .models import Book, BookSource, Folder, UploadBatch


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


class BookSerializer(serializers.ModelSerializer):
    source = BookSourceSerializer(read_only=True)
    path = serializers.CharField(read_only=True)

    class Meta:
        model = Book
        fields = ("id", "title", "folder", "path", "page_count", "has_text_layer",
                  "visibility", "thumbnail_path", "source", "deleted_at",
                  "created_at", "updated_at")
        read_only_fields = ("id", "path", "page_count", "has_text_layer", "thumbnail_path",
                            "source", "deleted_at", "created_at", "updated_at")

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
