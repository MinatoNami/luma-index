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
from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Book, Folder, UploadBatch
from .serializers import BookSerializer, FolderSerializer, UploadBatchSerializer
from .services import IngestError, store_upload
from .storage import InsufficientSpace, LibraryStorage

logger = logging.getLogger("lumaindex.library")

csrf_required = method_decorator(csrf_protect, name="dispatch")


class OwnedMixin:
    permission_classes = [IsAuthenticated]

    def folders(self):
        return Folder.objects.filter(owner=self.request.user)

    def books(self):
        return Book.objects.filter(owner=self.request.user).select_related("source", "folder")

    def get_folder(self, folder_id: int, *, live_only: bool = True) -> Folder:
        queryset = self.folders()
        if live_only:
            queryset = queryset.live()
        folder = queryset.filter(pk=folder_id).first()
        if folder is None:
            raise Http404
        return folder

    def get_book(self, book_id: int, *, live_only: bool = True) -> Book:
        queryset = self.books()
        if live_only:
            queryset = queryset.live()
        book = queryset.filter(pk=book_id).first()
        if book is None:
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

        if "folder" in request.GET:
            raw = request.GET["folder"]
            queryset = (queryset.filter(folder__isnull=True) if raw in ("", "root", "null")
                        else queryset.filter(folder_id=raw))

        if search := request.GET.get("search", "").strip():
            queryset = queryset.filter(title__icontains=search)

        sort = request.GET.get("sort", "title")
        allowed = {"title": "title", "-title": "-title", "added": "created_at",
                   "-added": "-created_at", "size": "source__file_size",
                   "-size": "-source__file_size"}
        queryset = queryset.order_by(allowed.get(sort, "title"))

        return Response(BookSerializer(queryset, many=True, context={"request": request}).data)


@csrf_required
class BookDetailView(OwnedMixin, APIView):
    @extend_schema(summary="One book", responses={200: BookSerializer})
    def get(self, request, book_id: int):
        return Response(BookSerializer(self.get_book(book_id),
                                       context={"request": request}).data)

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
    exposed as static content (PRD §18, §25, §29). FileResponse handles Range
    requests, which is what lets PDF.js open a large book without downloading
    all of it first.
    """

    @extend_schema(summary="Book contents (PDF)",
                   responses={200: OpenApiResponse(description="application/pdf")})
    def get(self, request, book_id: int):
        book = self.get_book(book_id)
        source = getattr(book, "source", None)
        if source is None:
            raise Http404

        path = LibraryStorage().path_for(source.storage_key)
        if not path.exists():
            logger.error("stored file is missing",
                         extra={"event": "library.content.missing", "book_id": book.pk})
            return Response({"detail": "The stored file is missing."},
                            status=status.HTTP_410_GONE)

        response = FileResponse(path.open("rb"), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{source.original_filename}"'
        response["Accept-Ranges"] = "bytes"
        return response


class BookThumbnailView(OwnedMixin, APIView):
    @extend_schema(summary="Book thumbnail",
                   responses={200: OpenApiResponse(description="image/webp")})
    def get(self, request, book_id: int):
        book = self.get_book(book_id)
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
        responses={201: OpenApiResponse(description="Imported books, or a queued batch")},
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
            except InsufficientSpace as exc:
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
            except InsufficientSpace as exc:
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
# Trash and storage
# --------------------------------------------------------------------------- #

class TrashView(OwnedMixin, APIView):
    @extend_schema(summary="Trashed folders and books",
                   responses={200: OpenApiResponse(description="Trash contents")})
    def get(self, request):
        folders = self.folders().trashed()
        books = self.books().trashed()
        return Response({
            "folders": FolderSerializer(folders, many=True, context={"request": request}).data,
            "books": BookSerializer(books, many=True, context={"request": request}).data,
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
        })
