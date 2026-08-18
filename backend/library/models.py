"""Folders, books, and the files behind them.

LumaIndex owns its storage: users upload PDFs and organise them in folders,
the way they would in a file manager. Two shapes carry over from the PRD and
still earn their place:

* `Book` is separate from `BookSource` (PRD §14), so the reader and library
  domains do not care where bytes live. That kept Drive replaceable, and it is
  what will keep a second provider — or a re-upload of a better scan — from
  touching annotations.
* Books are private by default (PRD §16).

Deletion is a trash: nothing is destroyed until it is emptied. An uploaded PDF
may be the only copy the user has, so an accidental click must be recoverable.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Folders nest, but not without limit: an unbounded tree makes breadcrumb and
# descendant queries unbounded too.
MAX_FOLDER_DEPTH = 16


class TrashQuerySet(models.QuerySet):
    def live(self):
        return self.filter(deleted_at__isnull=True)

    def trashed(self):
        return self.filter(deleted_at__isnull=False)


class Folder(models.Model):
    """A user-owned folder. `parent` of None means the top level."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders"
    )
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TrashQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            # Two constraints rather than one, because PostgreSQL treats NULLs
            # as distinct: a single UNIQUE(owner, parent, name) would happily
            # allow two folders called "Books" at the top level.
            models.UniqueConstraint(
                fields=["owner", "parent", "name"],
                condition=Q(deleted_at__isnull=True, parent__isnull=False),
                name="unique_live_folder_name_in_parent",
            ),
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=Q(deleted_at__isnull=True, parent__isnull=True),
                name="unique_live_folder_name_at_root",
            ),
        ]
        indexes = [models.Index(fields=["owner", "parent"])]

    def __str__(self) -> str:
        return self.name

    # -- tree ------------------------------------------------------------- #

    def ancestors(self) -> list[Folder]:
        """Root-first chain above this folder."""
        chain: list[Folder] = []
        seen: set[int] = set()
        node = self.parent
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    @property
    def path(self) -> str:
        return "/".join([*(f.name for f in self.ancestors()), self.name])

    @property
    def depth(self) -> int:
        return len(self.ancestors())

    def descendant_ids(self) -> list[int]:
        """Every folder beneath this one, itself excluded."""
        found: list[int] = []
        frontier = [self.pk]
        while frontier:
            children = list(
                Folder.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            children = [pk for pk in children if pk not in found and pk != self.pk]
            if not children:
                break
            found.extend(children)
            frontier = children
        return found

    def clean(self):
        if self.parent_id is None:
            return
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "A folder cannot be inside itself."})
        if self.pk and self.parent_id in set(self.descendant_ids()):
            # Allowing this detaches the whole subtree from the root and makes
            # every ancestor walk loop forever.
            raise ValidationError({"parent": "A folder cannot be moved inside its own subfolder."})
        if self.parent.owner_id != self.owner_id:
            raise ValidationError({"parent": "The parent folder belongs to another user."})
        if self.parent.depth + 1 >= MAX_FOLDER_DEPTH:
            raise ValidationError({"parent": f"Folders may nest at most {MAX_FOLDER_DEPTH} deep."})

    # -- trash ------------------------------------------------------------- #

    def trash(self, *, at=None) -> dict[str, int]:
        """Move this folder, its subfolders, and their books to the trash."""
        at = at or timezone.now()
        ids = [self.pk, *self.descendant_ids()]
        folders = Folder.objects.filter(pk__in=ids, deleted_at__isnull=True).update(deleted_at=at)
        books = Book.objects.filter(folder_id__in=ids, deleted_at__isnull=True).update(
            deleted_at=at
        )
        return {"folders": folders, "books": books}

    def restore(self) -> dict[str, int]:
        """Restore this folder and everything trashed along with it.

        Only items trashed at the same moment come back, so restoring a folder
        does not resurrect a book the user deleted separately beforehand.
        """
        at = self.deleted_at
        if at is None:
            return {"folders": 0, "books": 0}

        # An ancestor still in the trash would leave this folder unreachable.
        for ancestor in self.ancestors():
            if ancestor.deleted_at is not None:
                raise ValidationError(
                    "Restore the parent folder first — this one would have nowhere to live."
                )

        ids = [self.pk, *self.descendant_ids()]
        folders = Folder.objects.filter(pk__in=ids, deleted_at=at).update(deleted_at=None)
        books = Book.objects.filter(folder_id__in=ids, deleted_at=at).update(deleted_at=None)
        return {"folders": folders, "books": books}


class Book(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        SHARED = "shared", "Shared with instance"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="books"
    )
    # None means the top level, mirroring Folder.parent.
    folder = models.ForeignKey(
        Folder, on_delete=models.CASCADE, null=True, blank=True, related_name="books"
    )

    title = models.CharField(max_length=512)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    # None = not probed yet. False drives the PRD §27 "search unavailable"
    # message rather than letting a search silently return nothing.
    has_text_layer = models.BooleanField(null=True, blank=True)

    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    thumbnail_path = models.CharField(max_length=512, blank=True)

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TrashQuerySet.as_manager()

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["owner", "folder"]),
            models.Index(fields=["visibility"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_shared(self) -> bool:
        return self.visibility == self.Visibility.SHARED

    @property
    def path(self) -> str:
        return f"{self.folder.path}/{self.title}" if self.folder_id else self.title

    def trash(self, *, at=None) -> None:
        self.deleted_at = at or timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self) -> None:
        if self.folder_id and self.folder.deleted_at is not None:
            raise ValidationError(
                "Restore the folder first — this book would have nowhere to live."
            )
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])


class BookSource(models.Model):
    """The stored file behind a book."""

    class Provider(models.TextChoices):
        LOCAL_UPLOAD = "local_upload", "Uploaded"

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available"
        MISSING = "missing", "File missing from storage"
        ERROR = "error", "Unreadable"

    book = models.OneToOneField(Book, on_delete=models.CASCADE, related_name="source")
    provider = models.CharField(
        max_length=32, choices=Provider.choices, default=Provider.LOCAL_UPLOAD
    )

    # SHA-256 of the file's contents, and its identity in the blob store.
    # Content addressing means uploading the same file twice stores one copy —
    # so retrying a half-finished ZIP import costs no extra disk.
    storage_key = models.CharField(max_length=64, db_index=True)

    original_filename = models.CharField(max_length=512)
    content_type = models.CharField(max_length=128, blank=True)
    file_size = models.BigIntegerField(default=0)

    availability_status = models.CharField(
        max_length=16, choices=Availability.choices, default=Availability.AVAILABLE
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["availability_status"])]

    def __str__(self) -> str:
        return self.original_filename

    @property
    def is_available(self) -> bool:
        return self.availability_status == self.Availability.AVAILABLE


class ReadingProgress(models.Model):
    """Where a reader is in a book.

    Per-user and private (PRD §19): sharing a book shares the file, never the
    place someone had got to.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reading_progress"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="progress_records")

    page = models.PositiveIntegerField(default=0)  # 0-indexed
    # How far through that page, rather than a pixel offset. A pixel offset
    # means nothing at a different zoom or on a different screen, which is
    # exactly what §21's cross-device resume has to survive.
    page_fraction = models.FloatField(default=0.0)
    # Denormalised for library cards, and computed on the server so two clients
    # cannot disagree about it.
    percentage = models.FloatField(default=0.0)

    last_opened_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # The client's own clock at the moment it recorded this position. Used only
    # to reject a stale write — see the progress endpoint.
    client_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="unique_progress_per_reader")
        ]
        indexes = [
            models.Index(fields=["user", "-last_opened_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.percentage:.0f}% of {self.book}"

    @property
    def is_finished(self) -> bool:
        return self.percentage >= 99.5

    @property
    def is_started(self) -> bool:
        return 0 < self.percentage < 99.5


class Bookmark(models.Model):
    """A remembered place. Private to the reader who made it (PRD §22)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks"
    )
    # Bookmarks hang off the Book, never the BookSource: PRD §13 requires a
    # file going missing to leave a reader's notes intact, and pointing at the
    # source would delete them with it.
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="bookmarks")

    page = models.PositiveIntegerField()
    page_fraction = models.FloatField(default=0.0)
    label = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["page"]
        indexes = [models.Index(fields=["user", "book", "page"])]
        constraints = [
            models.UniqueConstraint(fields=["user", "book", "page"],
                                    name="one_bookmark_per_page")
        ]

    def __str__(self) -> str:
        return self.label or f"page {self.page + 1}"


class Highlight(models.Model):
    """Highlighted text, optionally with a note attached.

    `position_data` is versioned from the first write. Once readers have
    highlights the coordinates cannot be recomputed — the mapping depended on a
    viewport that no longer exists — so the shape has to be right now rather
    than migrated later. See docs/phases/05-reading-data.md.
    """

    class Colour(models.TextChoices):
        YELLOW = "yellow", "Yellow"
        GREEN = "green", "Green"
        BLUE = "blue", "Blue"
        PINK = "pink", "Pink"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="highlights"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="highlights")

    page = models.PositiveIntegerField()
    selected_text = models.TextField(blank=True)
    # {"v": 1, "quads": [{"x1","y1","x2","y2"}, ...], "text_offsets": {...}}
    # Quads in PDF user space, so a highlight means the same thing at any zoom
    # and on any screen (PRD §23).
    position_data = models.JSONField(default=dict)
    colour = models.CharField(max_length=16, choices=Colour.choices, default=Colour.YELLOW)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page", "created_at"]
        indexes = [models.Index(fields=["user", "book", "page"])]

    def __str__(self) -> str:
        return self.selected_text[:60] or f"highlight on page {self.page + 1}"


class PageNote(models.Model):
    """A note about a page rather than about a passage.

    Exists because §27 defers OCR: a scanned book has no text layer, so a
    text-anchored highlight is impossible there. Without page notes the feature
    would be missing from exactly the books most likely to need one.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="page_notes"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="page_notes")

    page = models.PositiveIntegerField()
    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page", "created_at"]
        indexes = [models.Index(fields=["user", "book", "page"])]

    def __str__(self) -> str:
        return self.body[:60]


class UploadBatch(models.Model):
    """One upload the worker has to chew through.

    A ZIP of a few hundred books takes minutes to extract, probe, and
    thumbnail, so the request stages the file and returns; this row is what the
    UI polls and what an admin reads when an import went wrong.
    """

    class Kind(models.TextChoices):
        ZIP = "zip", "ZIP archive"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        RUNNING = "running", "Running"
        OK = "ok", "Completed"
        PARTIAL = "partial", "Completed with problems"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_batches"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.ZIP)
    original_filename = models.CharField(max_length=512)
    target_folder = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="upload_batches"
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    staged_path = models.CharField(max_length=1024, blank=True)

    discovered = models.PositiveIntegerField(default=0)
    imported = models.PositiveIntegerField(default=0)
    skipped_duplicate = models.PositiveIntegerField(default=0)
    skipped_unsupported = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)

    error_summary = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"]),
                   models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.status})"

    @property
    def counts(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "imported": self.imported,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_unsupported": self.skipped_unsupported,
            "failed": self.failed,
        }
