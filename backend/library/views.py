"""Library endpoints: folders, books, uploads, trash.

Every queryset here starts from the requesting user. PRD §29 requires
authorization on the server, and the reliable way to honour that is for there
to be no code path that begins with `Book.objects.all()`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FileUploadParser, FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import bulk, chunked, sorting
from .lifecycle import readers_of, set_visibility
from .models import (
    Book,
    Bookmark,
    ChunkedUpload,
    Collection,
    CollectionBook,
    Folder,
    Highlight,
    PageNote,
    ReadingProgress,
    UploadBatch,
    UserBookState,
)
from .outline import outline_for
from .permissions import can_modify, can_read, readable_books
from .quota import QuotaExceeded, ensure_room, limit_for, usage_for
from .ranges import serve_file
from .retention import retention_days
from .serializers import (
    BookmarkSerializer,
    BookSerializer,
    BulkActionSerializer,
    ChunkedUploadStartSerializer,
    CollectionSerializer,
    FolderSerializer,
    HighlightSerializer,
    PageNoteSerializer,
    ProgressWriteSerializer,
    ReadingProgressSerializer,
    SharedBookSerializer,
    UploadBatchSerializer,
    UploadRequestSerializer,
)
from .services import IngestError, store_upload
from .storage import InsufficientSpace, LibraryStorage

logger = logging.getLogger("lumaindex.library")

csrf_required = method_decorator(csrf_protect, name="dispatch")


class OwnedMixin:
    permission_classes = [IsAuthenticated]

    def folders(self):
        return Folder.objects.filter(owner=self.request.user)

    def books(self):
        from django.db.models import Prefetch

        # Prefetched rather than fetched per card: a folder of 200 books would
        # otherwise be 200 extra queries.
        return (
            Book.objects.filter(owner=self.request.user)
            .select_related("source", "folder")
            .prefetch_related(
                Prefetch(
                    "progress_records",
                    queryset=ReadingProgress.objects.filter(user=self.request.user),
                    to_attr="_reader_progress",
                ),
                Prefetch(
                    "reader_states",
                    queryset=UserBookState.objects.filter(user=self.request.user),
                    to_attr="_reader_state",
                ),
            )
        )

    def get_folder(self, folder_id: int, *, live_only: bool = True) -> Folder:
        queryset = self.folders()
        if live_only:
            queryset = queryset.live()
        folder = queryset.filter(pk=folder_id).first()
        if folder is None:
            raise Http404
        return folder

    def get_book(self, book_id: int, *, live_only: bool = True) -> Book:
        """A book the caller owns. Use `get_readable_book` for reading paths."""
        queryset = self.books()
        if live_only:
            queryset = queryset.live()
        book = queryset.filter(pk=book_id).first()
        if book is None:
            raise Http404
        return book

    def get_readable_book(self, book_id: int) -> Book:
        """A book the caller may open — theirs, or one shared with the instance.

        404 rather than 403 for anything else: a 403 would confirm the book
        exists, which is itself a leak.
        """
        from django.db.models import Prefetch

        book = (
            readable_books(self.request.user)
            .select_related("source", "folder", "owner")
            .prefetch_related(Prefetch(
                "progress_records",
                queryset=ReadingProgress.objects.filter(user=self.request.user),
                to_attr="_reader_progress",
            ))
            .filter(pk=book_id)
            .first()
        )
        if book is None or not can_read(self.request.user, book):
            raise Http404
        return book


# --------------------------------------------------------------------------- #
# Folders
# --------------------------------------------------------------------------- #

@csrf_required
class FolderListView(OwnedMixin, APIView):
    @extend_schema(summary="Folders", responses={200: FolderSerializer(many=True)})
    def get(self, request):
        queryset = self.folders().live()
        if "parent" in request.GET:
            raw = request.GET["parent"]
            queryset = (queryset.filter(parent__isnull=True) if raw in ("", "root", "null")
                        else queryset.filter(parent_id=raw))
        queryset = sorting.apply(queryset, request.GET.get("sort"), sorting.FOLDER_FIELDS)
        return Response(FolderSerializer(queryset, many=True, context={"request": request}).data)

    @extend_schema(summary="Create a folder", request=FolderSerializer,
                   responses={201: FolderSerializer})
    def post(self, request):
        serializer = FolderSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        folder = Folder(owner=request.user, **serializer.validated_data)
        return self._save(folder, serializer, status.HTTP_201_CREATED)

    def _save(self, folder: Folder, serializer, ok_status: int):
        try:
            folder.full_clean(exclude=["owner"])
            folder.save()
        except DjangoValidationError as exc:
            return Response({"detail": "; ".join(sum(exc.message_dict.values(), []))},
                            status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response({"detail": "A folder with that name already exists here."},
                            status=status.HTTP_409_CONFLICT)
        return Response(FolderSerializer(folder, context=serializer.context).data,
                        status=ok_status)


@csrf_required
class FolderDetailView(OwnedMixin, APIView):
    @extend_schema(summary="One folder", responses={200: FolderSerializer})
    def get(self, request, folder_id: int):
        folder = self.get_folder(folder_id)
        data = FolderSerializer(folder, context={"request": request}).data
        data["ancestors"] = FolderSerializer(folder.ancestors(), many=True,
                                             context={"request": request}).data
        return Response(data)

    @extend_schema(summary="Rename or move a folder", request=FolderSerializer,
                   responses={200: FolderSerializer})
    def patch(self, request, folder_id: int):
        folder = self.get_folder(folder_id)
        serializer = FolderSerializer(folder, data=request.data, partial=True,
                                      context={"request": request})
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(folder, field, value)
        return FolderListView._save(self, folder, serializer, status.HTTP_200_OK)

    @extend_schema(
        summary="Move a folder to the trash",
        responses={200: OpenApiResponse(description="Trashed, with counts")},
    )
    def delete(self, request, folder_id: int):
        folder = self.get_folder(folder_id, live_only=False)

        # ?permanent=true empties this branch of the trash for good. Anything
        # else is the reversible path, which is what a stray click should hit.
        if request.GET.get("permanent") == "true":
            if folder.deleted_at is None:
                return Response(
                    {"detail": "Move the folder to the trash before deleting it permanently."},
                    status=status.HTTP_409_CONFLICT,
                )
            removed = self._purge(folder)
            return Response({"deleted": removed})

        counts = folder.trash()
        logger.info("folder trashed", extra={"event": "library.folder.trashed",
                                             "folder_id": folder.pk, **counts})
        return Response({"trashed": counts})

    def _purge(self, folder: Folder) -> dict[str, int]:
        storage = LibraryStorage()
        ids = [folder.pk, *folder.descendant_ids()]
        keys = list(
            Book.objects.filter(owner=self.request.user, folder_id__in=ids)
            .values_list("source__storage_key", flat=True)
        )
        books = Book.objects.filter(owner=self.request.user, folder_id__in=ids).count()
        Folder.objects.filter(pk__in=ids).delete()   # cascades to books and sources
        for key in filter(None, keys):
            storage.delete_if_unreferenced(key)
        return {"folders": len(ids), "books": books}


@csrf_required
class FolderRestoreView(OwnedMixin, APIView):
    @extend_schema(summary="Restore a folder from the trash", request=None,
                   responses={200: OpenApiResponse(description="Restored, with counts")})
    def post(self, request, folder_id: int):
        folder = self.get_folder(folder_id, live_only=False)
        try:
            counts = folder.restore()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        return Response({"restored": counts})


# --------------------------------------------------------------------------- #
# Books
# --------------------------------------------------------------------------- #

class BookListView(OwnedMixin, APIView):
    @extend_schema(summary="Books", responses={200: BookSerializer(many=True)})
    def get(self, request):
        queryset = self.books().live()

        # The virtual views from PRD §12, as a filter rather than magic
        # collection ids — otherwise every collection endpoint grows special
        # cases for values that are not collections.
        view = request.GET.get("view")
        if view == "favourites":
            queryset = queryset.filter(reader_states__user=request.user,
                                       reader_states__is_favourite=True)
        elif view == "recent":
            queryset = queryset.order_by("-created_at")[:50]
            return Response(BookSerializer(queryset, many=True,
                                           context={"request": request}).data)
        elif view == "unsorted":
            # In no collection at all — the pile you have not filed yet.
            queryset = queryset.filter(memberships__isnull=True)
        elif "collection" in request.GET:
            queryset = queryset.filter(memberships__collection_id=request.GET["collection"],
                                       memberships__collection__owner=request.user)

        if "folder" in request.GET:
            raw = request.GET["folder"]
            queryset = (queryset.filter(folder__isnull=True) if raw in ("", "root", "null")
                        else queryset.filter(folder_id=raw))

        if search := request.GET.get("search", "").strip():
            queryset = queryset.filter(title__icontains=search)

        queryset = sorting.apply(queryset, request.GET.get("sort"), sorting.BOOK_FIELDS)

        return Response(BookSerializer(queryset, many=True, context={"request": request}).data)


@csrf_required
class BookDetailView(OwnedMixin, APIView):
    @extend_schema(summary="One book", responses={200: BookSerializer})
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        # A non-owner gets the reader's view, which omits the owner's filename
        # and folder path.
        serializer = (BookSerializer if book.owner_id == request.user.pk
                      else SharedBookSerializer)
        return Response(serializer(book, context={"request": request}).data)

    @extend_schema(summary="Rename or move a book", request=BookSerializer,
                   responses={200: BookSerializer})
    def patch(self, request, book_id: int):
        book = self.get_book(book_id)
        serializer = BookSerializer(book, data=request.data, partial=True,
                                    context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(summary="Move a book to the trash",
                   responses={204: OpenApiResponse(description="Trashed")})
    def delete(self, request, book_id: int):
        book = self.get_book(book_id, live_only=False)

        if request.GET.get("permanent") == "true":
            if book.deleted_at is None:
                return Response(
                    {"detail": "Move the book to the trash before deleting it permanently."},
                    status=status.HTTP_409_CONFLICT,
                )
            key = book.source.storage_key if hasattr(book, "source") else ""
            book.delete()
            if key:
                # Only removes the file if no other book shares those bytes.
                LibraryStorage().delete_if_unreferenced(key)
            return Response(status=status.HTTP_204_NO_CONTENT)

        book.trash()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class BookRestoreView(OwnedMixin, APIView):
    @extend_schema(summary="Restore a book", request=None, responses={200: BookSerializer})
    def post(self, request, book_id: int):
        book = self.get_book(book_id, live_only=False)
        try:
            book.restore()
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        return Response(BookSerializer(book, context={"request": request}).data)


class BookContentView(OwnedMixin, APIView):
    """Stream a stored PDF.

    Django authorizes before a byte moves, and the storage directory is never
    exposed as static content (PRD §18, §25, §29).

    Byte ranges are honoured here rather than left to FileResponse, which
    ignores them: PDF.js reads a PDF's trailer from the end of the file before
    anything else, and without a 206 it downloads the whole book first.
    """

    @extend_schema(summary="Book contents (PDF)",
                   responses={200: OpenApiResponse(description="application/pdf"),
                              206: OpenApiResponse(description="Partial content"),
                              416: OpenApiResponse(description="Range not satisfiable")})
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        source = getattr(book, "source", None)
        if source is None:
            raise Http404

        path = LibraryStorage().path_for(source.storage_key)
        if not path.exists():
            logger.error("stored file is missing",
                         extra={"event": "library.content.missing", "book_id": book.pk})
            return Response({"detail": "The stored file is missing."},
                            status=status.HTTP_410_GONE)

        response = serve_file(
            path,
            content_type="application/pdf",
            filename=source.original_filename,
            range_header=request.headers.get("Range", ""),
        )
        # X_FRAME_OPTIONS is DENY globally, which is right for the app but also
        # blocks our own reader from embedding this. Relaxed to same-origin on
        # this one response so the PDF can be displayed in place.
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response


class BookThumbnailView(OwnedMixin, APIView):
    @extend_schema(summary="Book thumbnail",
                   responses={200: OpenApiResponse(description="image/webp")})
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        if not book.thumbnail_path:
            raise Http404

        path = Path(settings.THUMBNAIL_DIR) / book.thumbnail_path
        # A thumbnail of a private book is still private, so it is served
        # through here rather than from a static directory.
        if not path.resolve().is_relative_to(Path(settings.THUMBNAIL_DIR).resolve()):
            raise Http404
        if not path.exists():
            raise Http404

        response = FileResponse(path.open("rb"), content_type="image/webp")
        response["Cache-Control"] = "private, max-age=86400"
        return response


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #

@csrf_required
class UploadView(OwnedMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Upload PDFs or a ZIP archive",
        request=UploadRequestSerializer,
        responses={201: OpenApiResponse(description="Imported books, or a queued batch"),
                   507: OpenApiResponse(description="Out of disk space, or over quota")},
    )
    def post(self, request):
        folder = None
        if raw := request.data.get("folder"):
            folder = self.get_folder(int(raw))

        uploads = request.FILES.getlist("files") or (
            [request.FILES["file"]] if "file" in request.FILES else []
        )
        if not uploads:
            return Response({"detail": "No file was uploaded."},
                            status=status.HTTP_400_BAD_REQUEST)

        archives = [f for f in uploads if (f.name or "").lower().endswith(".zip")]
        pdfs = [f for f in uploads if f not in archives]

        results: dict = {"imported": [], "duplicates": 0, "batches": [], "errors": []}
        storage = LibraryStorage()

        for upload in pdfs:
            try:
                book, outcome = store_upload(request.user, upload, folder=folder,
                                             storage=storage)
            except (InsufficientSpace, QuotaExceeded) as exc:
                return Response({"detail": str(exc)},
                                status=status.HTTP_507_INSUFFICIENT_STORAGE)
            except IngestError as exc:
                results["errors"].append(f"{upload.name}: {exc}")
                continue

            if outcome == "duplicate":
                results["duplicates"] += 1
            else:
                results["imported"].append(
                    BookSerializer(book, context={"request": request}).data
                )

        for archive in archives:
            try:
                batch = self._stage(request, archive, folder, storage)
            except (InsufficientSpace, QuotaExceeded) as exc:
                return Response({"detail": str(exc)},
                                status=status.HTTP_507_INSUFFICIENT_STORAGE)
            results["batches"].append(
                UploadBatchSerializer(batch, context={"request": request}).data
            )

        code = status.HTTP_201_CREATED if (results["imported"] or results["batches"]) \
            else status.HTTP_200_OK
        return Response(results, status=code)

    def _stage(self, request, archive, folder, storage) -> UploadBatch:
        """Park an archive on disk for the worker.

        Extracting inline would hold a gunicorn worker for the length of a
        several-hundred-book import and time out long before finishing.
        """
        max_bytes = int(getattr(settings, "MAX_UPLOAD_BYTES", 0))
        if max_bytes and archive.size > max_bytes:
            raise IngestError(f"That archive exceeds the {max_bytes // 1024**2} MiB limit.")
        storage.check_space_for(archive.size)
        # The archive's own bytes are not charged — they are deleted once read —
        # but an account with no room left should hear so now rather than after
        # the worker has extracted four hundred books it cannot keep.
        ensure_room(request.user)

        staging = Path(settings.UPLOAD_STAGING_DIR)
        staging.mkdir(parents=True, exist_ok=True)

        batch = UploadBatch.objects.create(
            owner=request.user, kind=UploadBatch.Kind.ZIP,
            original_filename=(archive.name or "upload.zip")[:512], target_folder=folder,
        )
        destination = staging / f"batch-{batch.pk}.zip"
        with destination.open("wb") as out:
            for chunk in archive.chunks():
                out.write(chunk)

        batch.staged_path = str(destination)
        batch.save(update_fields=["staged_path"])
        logger.info("archive staged", extra={"event": "library.upload.staged",
                                             "batch_id": batch.pk})
        return batch


@csrf_required
class ChunkedUploadStartView(OwnedMixin, APIView):
    """Begin a large upload.

    Everything that could refuse the file — its size, the free disk, the
    account's quota — is checked now. Refusing here costs nothing; refusing
    after four minutes of uploading costs the whole thing.
    """

    @extend_schema(
        summary="Start a chunked upload",
        request=ChunkedUploadStartSerializer,
        responses={201: OpenApiResponse(description="Where to send the first chunk"),
                   507: OpenApiResponse(description="Out of disk space, or over quota")},
    )
    def post(self, request):
        form = ChunkedUploadStartSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        folder = self.get_folder(form.validated_data["folder"]) \
            if form.validated_data.get("folder") else None

        try:
            upload = chunked.begin(request.user, filename=form.validated_data["filename"],
                                   size=form.validated_data["size"], folder=folder)
        except (InsufficientSpace, QuotaExceeded) as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_507_INSUFFICIENT_STORAGE)
        except IngestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_chunked_state(upload), status=status.HTTP_201_CREATED)


@csrf_required
class ChunkedUploadDetailView(OwnedMixin, APIView):
    """Send the next chunk, ask where to resume from, or give up."""

    parser_classes = [FileUploadParser]

    def get_upload(self, request, upload_id: int) -> ChunkedUpload:
        upload = ChunkedUpload.objects.filter(pk=upload_id, owner=request.user).first()
        if upload is None:
            raise Http404
        return upload

    @extend_schema(summary="How much of this upload has arrived",
                   responses={200: OpenApiResponse(description="Resume point")})
    def get(self, request, upload_id: int):
        return Response(_chunked_state(self.get_upload(request, upload_id)))

    @extend_schema(
        summary="Append a chunk",
        request={"application/octet-stream": {"type": "string", "format": "binary"}},
        responses={200: OpenApiResponse(description="Accepted, with the new resume point"),
                   409: OpenApiResponse(description="Sent from the wrong offset")},
    )
    def put(self, request, upload_id: int):
        upload = self.get_upload(request, upload_id)
        try:
            offset = int(request.GET.get("offset", ""))
        except ValueError:
            return Response({"detail": "Say which byte this chunk starts at."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            received = chunked.append(upload, offset=offset, stream=request.stream)
        except chunked.ChunkConflict as exc:
            # 409 with the real resume point, so a client that lost a response
            # or retried out of order can correct itself in one round trip.
            return Response({"detail": str(exc), "received": exc.received},
                            status=status.HTTP_409_CONFLICT)
        except IngestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_410_GONE)

        return Response({"id": upload.pk, "received": received,
                         "size": upload.declared_size})

    @extend_schema(summary="Abandon an upload",
                   responses={204: OpenApiResponse(description="Discarded")})
    def delete(self, request, upload_id: int):
        chunked.abandon(self.get_upload(request, upload_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class ChunkedUploadCompleteView(OwnedMixin, APIView):
    """Turn a finished upload into a book, through the ordinary path."""

    @extend_schema(summary="Complete a chunked upload", request=None,
                   responses={201: BookSerializer,
                              409: OpenApiResponse(description="Still missing bytes")})
    def post(self, request, upload_id: int):
        upload = ChunkedUpload.objects.filter(pk=upload_id, owner=request.user).first()
        if upload is None:
            raise Http404

        try:
            book, outcome = chunked.finish(upload)
        except chunked.ChunkConflict as exc:
            return Response({"detail": str(exc), "received": exc.received},
                            status=status.HTTP_409_CONFLICT)
        except (InsufficientSpace, QuotaExceeded) as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_507_INSUFFICIENT_STORAGE)
        except IngestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"outcome": outcome,
             "book": BookSerializer(book, context={"request": request}).data},
            status=status.HTTP_201_CREATED,
        )


def _chunked_state(upload: ChunkedUpload) -> dict:
    return {"id": upload.pk, "received": upload.received,
            "size": upload.declared_size, "chunk_size": chunked.CHUNK_SIZE}


class UploadBatchListView(OwnedMixin, APIView):
    @extend_schema(summary="Recent uploads", responses={200: UploadBatchSerializer(many=True)})
    def get(self, request):
        batches = UploadBatch.objects.filter(owner=request.user)[:20]
        return Response(UploadBatchSerializer(batches, many=True,
                                              context={"request": request}).data)


class UploadBatchDetailView(OwnedMixin, APIView):
    @extend_schema(summary="One upload batch", responses={200: UploadBatchSerializer})
    def get(self, request, batch_id: int):
        batch = UploadBatch.objects.filter(pk=batch_id, owner=request.user).first()
        if batch is None:
            raise Http404
        return Response(UploadBatchSerializer(batch, context={"request": request}).data)


# --------------------------------------------------------------------------- #
# Acting on a selection
# --------------------------------------------------------------------------- #

@csrf_required
class BulkActionView(OwnedMixin, APIView):
    """One action across a selection of folders and books.

    Always 200 with a report, never a partial 4xx: the interesting answer is
    "eight moved, two were already there", and an error status would throw
    away the eight.
    """

    @extend_schema(
        summary="Act on several items at once",
        request=BulkActionSerializer,
        responses={200: OpenApiResponse(description="Counts, and anything skipped")},
    )
    def post(self, request):
        form = BulkActionSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        action = data["action"]
        folders, books = data["folders"], data["books"]

        if action == "move":
            target = self.get_folder(data["folder"]) if data.get("folder") else None
            result = bulk.move(request.user, folders, books, target)
        elif action == "trash":
            result = bulk.trash(request.user, folders, books)
        elif action in ("favourite", "unfavourite"):
            result = bulk.set_favourite(request.user, books, action == "favourite")
        else:
            collection = CollectionDetailView.get_collection(self, request, data["collection"])
            result = bulk.add_to_collection(request.user, books, collection)

        logger.info("bulk action", extra={"event": "library.bulk", "action": action,
                                          **result.as_dict(), "skipped": len(result.skipped)})
        return Response(result.as_dict())


# --------------------------------------------------------------------------- #
# Trash and storage
# --------------------------------------------------------------------------- #

class TrashView(OwnedMixin, APIView):
    @extend_schema(summary="Trashed folders and books",
                   responses={200: OpenApiResponse(description="Trash contents")})
    def get(self, request):
        # Most recently thrown away first: the thing you are looking for in a
        # trash is almost always the thing you just deleted by mistake.
        sort = request.GET.get("sort", "-trashed")
        folders = sorting.apply(self.folders().trashed(), sort, sorting.FOLDER_FIELDS)
        books = sorting.apply(self.books().trashed(), sort, sorting.BOOK_FIELDS)
        return Response({
            "folders": FolderSerializer(folders, many=True, context={"request": request}).data,
            "books": BookSerializer(books, many=True, context={"request": request}).data,
            # Null when retention is off, which is the default.
            "retention_days": retention_days() or None,
        })


class StorageStatusView(OwnedMixin, APIView):
    @extend_schema(summary="Storage usage", responses={200: OpenApiResponse()})
    def get(self, request):
        storage = LibraryStorage()
        return Response({
            "free_bytes": storage.free_bytes(),
            "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
            "min_free_disk_bytes": settings.MIN_FREE_DISK_BYTES,
            "book_count": self.books().live().count(),
            # 0 means unlimited. Usage is reported either way — what your
            # library weighs is worth knowing without a limit on it.
            "quota_bytes": limit_for(request.user),
            "used_bytes": usage_for(request.user),
        })


class BookOutlineView(OwnedMixin, APIView):
    """The PDF's table of contents, where it has one (PRD §20)."""

    @extend_schema(summary="Book outline", responses={200: OpenApiResponse()})
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        source = getattr(book, "source", None)
        if source is None:
            raise Http404

        path = LibraryStorage().path_for(source.storage_key)
        if not path.exists():
            return Response({"items": []})
        return Response({"items": outline_for(path, source.storage_key)})


@csrf_required
class BookProgressView(OwnedMixin, APIView):
    """Where this reader is in this book.

    Progress is per-user (PRD §19) and there is no id but the caller's, so a
    reader can only ever read or write their own.
    """

    @extend_schema(summary="Reading progress", responses={200: ReadingProgressSerializer})
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        record = ReadingProgress.objects.filter(user=request.user, book=book).first()
        if record is None:
            return Response({"page": 0, "page_fraction": 0.0, "percentage": 0.0,
                             "last_opened_at": None, "updated_at": None,
                             "client_updated_at": None})
        return Response(ReadingProgressSerializer(record).data)

    @extend_schema(summary="Record reading progress", request=ProgressWriteSerializer,
                   responses={200: ReadingProgressSerializer})
    def put(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        serializer = ProgressWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            record, _ = ReadingProgress.objects.select_for_update().get_or_create(
                user=request.user, book=book,
            )

            incoming = data.get("client_updated_at")
            # The rule PRD §19 and §21 leave undefined. A device that was
            # backgrounded mid-book can flush its position long afterwards; if
            # that write is older than what the server already has, honouring it
            # would rewind a reader who has since moved on. Writes without a
            # client timestamp fall back to last-write-wins.
            if (incoming and record.client_updated_at
                    and incoming < record.client_updated_at):
                logger.info("ignored a stale progress write",
                            extra={"event": "reader.progress.stale", "book_id": book.pk})
                return Response(ReadingProgressSerializer(record).data)

            # Only clamp against a page count we actually have. A book opened
            # before the ingest worker has probed it has page_count None, and
            # treating that as a single page collapsed every position to 0.
            page = data["page"]
            if book.page_count:
                page = min(page, book.page_count - 1)
            record.page = page
            record.page_fraction = data["page_fraction"]
            record.percentage = self._percentage(page, data["page_fraction"], book.page_count)
            record.last_opened_at = timezone.now()
            record.client_updated_at = incoming
            record.save()

        return Response(ReadingProgressSerializer(record).data)

    @staticmethod
    def _percentage(page: int, fraction: float, page_count: int | None) -> float:
        if not page_count:
            return 0.0
        # Position of the reading point through the whole document, so a reader
        # halfway down the last page reads as ~100%, not (n-1)/n.
        return round(min(100.0, ((page + fraction) / page_count) * 100), 2)


class ContinueReadingView(OwnedMixin, APIView):
    """Books started but not finished, most recently opened first (PRD §12)."""

    @extend_schema(summary="Continue reading", responses={200: BookSerializer(many=True)})
    def get(self, request):
        records = (
            ReadingProgress.objects
            .filter(user=request.user, book__deleted_at__isnull=True,
                    percentage__gt=0, percentage__lt=99.5)
            .select_related("book", "book__source", "book__folder")
            .order_by("-last_opened_at")[:24]
        )
        books = []
        for record in records:
            book = record.book
            book._reader_progress = [record]
            books.append(book)
        return Response(BookSerializer(books, many=True, context={"request": request}).data)


class AnnotationListView(OwnedMixin, APIView):
    """List and create one kind of annotation on a book.

    Two checks on every request, not one: that the row belongs to the caller,
    and that the caller may still read the book it is on. They answer different
    questions — sharing can be revoked after an annotation was made (PRD §29).
    """

    model = None
    serializer_class = None

    def queryset_for(self, book):
        return self.model.objects.filter(user=self.request.user, book=book)

    @extend_schema(summary="List annotations")
    def get(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        queryset = self.queryset_for(book)
        if "page" in request.GET:
            # The reader asks per visible page; a heavily annotated 900-page
            # book is a lot of JSON to hand a phone all at once.
            queryset = queryset.filter(page=request.GET["page"])
        return Response(self.serializer_class(queryset, many=True).data)

    @extend_schema(summary="Create an annotation")
    def post(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(user=request.user, book=book)
        except IntegrityError:
            return Response({"detail": "That already exists."},
                            status=status.HTTP_409_CONFLICT)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AnnotationDetailView(OwnedMixin, APIView):
    model = None
    serializer_class = None

    def get_object(self, request, book_id: int, annotation_id: int):
        book = self.get_readable_book(book_id)
        obj = self.model.objects.filter(
            pk=annotation_id, user=request.user, book=book,
        ).first()
        if obj is None:
            raise Http404
        return obj

    @extend_schema(summary="Update an annotation")
    def patch(self, request, book_id: int, annotation_id: int):
        obj = self.get_object(request, book_id, annotation_id)
        serializer = self.serializer_class(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(summary="Delete an annotation",
                   responses={204: OpenApiResponse(description="Deleted")})
    def delete(self, request, book_id: int, annotation_id: int):
        self.get_object(request, book_id, annotation_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class BookmarkListView(AnnotationListView):
    model = Bookmark
    serializer_class = BookmarkSerializer


@csrf_required
class BookmarkDetailView(AnnotationDetailView):
    model = Bookmark
    serializer_class = BookmarkSerializer


@csrf_required
class HighlightListView(AnnotationListView):
    model = Highlight
    serializer_class = HighlightSerializer


@csrf_required
class HighlightDetailView(AnnotationDetailView):
    model = Highlight
    serializer_class = HighlightSerializer


@csrf_required
class PageNoteListView(AnnotationListView):
    model = PageNote
    serializer_class = PageNoteSerializer


@csrf_required
class PageNoteDetailView(AnnotationDetailView):
    model = PageNote
    serializer_class = PageNoteSerializer


class SharedBooksView(OwnedMixin, APIView):
    """Books other people have shared with the instance (PRD §12, §16)."""

    @extend_schema(summary="Shared with me", responses={200: SharedBookSerializer(many=True)})
    def get(self, request):
        from django.db.models import Prefetch

        books = (
            Book.objects.live()
            .filter(visibility=Book.Visibility.SHARED)
            .exclude(owner=request.user)
            .select_related("owner")
            .prefetch_related(Prefetch(
                "progress_records",
                queryset=ReadingProgress.objects.filter(user=request.user),
                to_attr="_reader_progress",
            ))
            .order_by("title")
        )
        return Response(SharedBookSerializer(books, many=True,
                                             context={"request": request}).data)


@csrf_required
class BookShareView(OwnedMixin, APIView):
    """Change a book's visibility. Owner only."""

    @extend_schema(summary="Sharing status", responses={200: dict})
    def get(self, request, book_id: int):
        book = self.get_book(book_id)
        return Response({
            "visibility": book.visibility,
            # So the UI can say "2 other people have notes on this" before an
            # owner does something they cannot undo.
            "other_readers": readers_of(book).count(),
        })

    @extend_schema(summary="Share or unshare", request=dict, responses={200: dict})
    def post(self, request, book_id: int):
        book = self.get_book(book_id)
        if not can_modify(request.user, book):
            raise Http404

        visibility = request.data.get("visibility")
        if visibility not in dict(Book.Visibility.choices):
            return Response({"detail": "Unknown visibility."},
                            status=status.HTTP_400_BAD_REQUEST)

        set_visibility(book, request.user, visibility)
        return Response({"visibility": book.visibility,
                         "other_readers": readers_of(book).count()})


@csrf_required
class CollectionListView(OwnedMixin, APIView):
    """Collections are per-user; there is no id in the URL but the caller's."""

    def collections(self):
        return Collection.objects.filter(owner=self.request.user)

    @extend_schema(summary="Collections", responses={200: CollectionSerializer(many=True)})
    def get(self, request):
        queryset = self.collections()
        if "parent" in request.GET:
            raw = request.GET["parent"]
            queryset = (queryset.filter(parent__isnull=True) if raw in ("", "root", "null")
                        else queryset.filter(parent_id=raw))
        return Response(CollectionSerializer(queryset, many=True,
                                             context={"request": request}).data)

    @extend_schema(summary="Create a collection", request=CollectionSerializer,
                   responses={201: CollectionSerializer})
    def post(self, request):
        serializer = CollectionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        collection = Collection(owner=request.user, **serializer.validated_data)
        return self._save(collection, request, status.HTTP_201_CREATED)

    def _save(self, collection, request, ok_status):
        try:
            collection.full_clean(exclude=["owner"])
            collection.save()
        except DjangoValidationError as exc:
            return Response({"detail": "; ".join(sum(exc.message_dict.values(), []))},
                            status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response({"detail": "A collection with that name already exists here."},
                            status=status.HTTP_409_CONFLICT)
        return Response(CollectionSerializer(collection, context={"request": request}).data,
                        status=ok_status)


@csrf_required
class CollectionDetailView(OwnedMixin, APIView):
    def get_collection(self, request, collection_id: int) -> Collection:
        collection = Collection.objects.filter(pk=collection_id, owner=request.user).first()
        if collection is None:
            raise Http404
        return collection

    @extend_schema(summary="One collection", responses={200: CollectionSerializer})
    def get(self, request, collection_id: int):
        collection = self.get_collection(request, collection_id)
        data = CollectionSerializer(collection, context={"request": request}).data
        data["ancestors"] = CollectionSerializer(collection.ancestors(), many=True,
                                                 context={"request": request}).data
        return Response(data)

    @extend_schema(summary="Rename or move a collection", request=CollectionSerializer,
                   responses={200: CollectionSerializer})
    def patch(self, request, collection_id: int):
        collection = self.get_collection(request, collection_id)
        serializer = CollectionSerializer(collection, data=request.data, partial=True,
                                          context={"request": request})
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(collection, field, value)
        return CollectionListView._save(self, collection, request, status.HTTP_200_OK)

    @extend_schema(summary="Delete a collection",
                   responses={204: OpenApiResponse(description="Deleted")})
    def delete(self, request, collection_id: int):
        collection = self.get_collection(request, collection_id)
        # Removes the grouping, never the books in it. A collection is a view
        # onto a library, not a container that owns anything.
        collection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class CollectionBooksView(OwnedMixin, APIView):
    @extend_schema(summary="Books in a collection", responses={200: BookSerializer(many=True)})
    def get(self, request, collection_id: int):
        collection = CollectionDetailView.get_collection(self, request, collection_id)
        books = self.books().live().filter(memberships__collection=collection)
        return Response(BookSerializer(books, many=True, context={"request": request}).data)

    @extend_schema(summary="Add a book to a collection", request=dict,
                   responses={201: OpenApiResponse(description="Added")})
    def post(self, request, collection_id: int):
        collection = CollectionDetailView.get_collection(self, request, collection_id)
        book = self.get_readable_book(int(request.data.get("book_id", 0)))
        _, created = CollectionBook.objects.get_or_create(collection=collection, book=book)
        return Response({"added": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@csrf_required
class CollectionBookDetailView(OwnedMixin, APIView):
    @extend_schema(summary="Remove a book from a collection",
                   responses={204: OpenApiResponse(description="Removed")})
    def delete(self, request, collection_id: int, book_id: int):
        collection = CollectionDetailView.get_collection(self, request, collection_id)
        CollectionBook.objects.filter(collection=collection, book_id=book_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class BookFavouriteView(OwnedMixin, APIView):
    """Favourite is a flag, not a magic collection.

    A system-created collection would be renameable and deletable by the user,
    and a star icon pointing at a collection called something else is a bug
    report waiting to happen (see docs/phases/03-library.md).
    """

    @extend_schema(summary="Favourite a book", request=None,
                   responses={200: OpenApiResponse(description="Favourited")})
    def post(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        state, _ = UserBookState.objects.get_or_create(user=request.user, book=book)
        state.is_favourite = True
        state.save(update_fields=["is_favourite", "updated_at"])
        return Response({"is_favourite": True})

    @extend_schema(summary="Unfavourite a book",
                   responses={204: OpenApiResponse(description="Removed")})
    def delete(self, request, book_id: int):
        book = self.get_readable_book(book_id)
        UserBookState.objects.filter(user=request.user, book=book).update(is_favourite=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
