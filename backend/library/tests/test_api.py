"""Folder CRUD, uploads, and the authorization boundary around both."""

from __future__ import annotations

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from library.models import Book, Folder, UploadBatch
from library.services import process_pending_documents, process_zip_batch
from library.storage import LibraryStorage

from .pdfs import make_pdf
from .zips import build_zip, library_zip


def post(client, name, payload=None, args=None, **kwargs):
    return client.post(reverse(name, args=args or []), json.dumps(payload or {}),
                       content_type="application/json", headers=client.headers, **kwargs)


def patch(client, name, payload, args=None):
    return client.patch(reverse(name, args=args or []), json.dumps(payload),
                        content_type="application/json", headers=client.headers)


def upload(client, files, folder=None):
    data = {"files": files}
    if folder is not None:
        data["folder"] = str(folder)
    return client.post(reverse("library:upload"), data, headers=client.headers)


def pdf_file(name="Book.pdf", pages=1):
    return SimpleUploadedFile(name, make_pdf(pages=pages), content_type="application/pdf")


# -- folder CRUD ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_create_a_folder(api):
    response = post(api, "library:folders", {"name": "Books"})
    assert response.status_code == 201
    assert response.json()["name"] == "Books"
    assert response.json()["path"] == "Books"


@pytest.mark.django_db
def test_create_a_nested_folder(api, user):
    parent = Folder.objects.create(owner=user, name="Books")
    response = post(api, "library:folders", {"name": "Fiction", "parent": parent.pk})
    assert response.status_code == 201
    assert response.json()["path"] == "Books/Fiction"


@pytest.mark.django_db
def test_duplicate_names_in_one_parent_are_rejected(api, user):
    Folder.objects.create(owner=user, name="Books")
    assert post(api, "library:folders", {"name": "Books"}).status_code == 409


@pytest.mark.django_db
def test_rename_a_folder(api, user):
    folder = Folder.objects.create(owner=user, name="Bookz")
    response = patch(api, "library:folder-detail", {"name": "Books"}, args=[folder.pk])
    assert response.status_code == 200
    folder.refresh_from_db()
    assert folder.name == "Books"


@pytest.mark.django_db
def test_move_a_folder(api, user):
    books = Folder.objects.create(owner=user, name="Books")
    loose = Folder.objects.create(owner=user, name="Fiction")

    response = patch(api, "library:folder-detail", {"parent": books.pk}, args=[loose.pk])

    assert response.status_code == 200
    loose.refresh_from_db()
    assert loose.path == "Books/Fiction"


@pytest.mark.django_db
def test_a_folder_cannot_be_moved_into_its_own_subtree(api, user):
    books = Folder.objects.create(owner=user, name="Books")
    fiction = Folder.objects.create(owner=user, name="Fiction", parent=books)

    response = patch(api, "library:folder-detail", {"parent": fiction.pk}, args=[books.pk])

    assert response.status_code == 400
    books.refresh_from_db()
    assert books.parent_id is None


@pytest.mark.django_db
def test_a_folder_name_cannot_contain_a_slash(api):
    assert post(api, "library:folders", {"name": "Books/Fiction"}).status_code == 400


@pytest.mark.django_db
def test_folders_can_be_listed_by_parent(api, user):
    books = Folder.objects.create(owner=user, name="Books")
    Folder.objects.create(owner=user, name="Fiction", parent=books)
    Folder.objects.create(owner=user, name="Loose")

    root = api.get(reverse("library:folders"), {"parent": "root"}).json()
    assert {f["name"] for f in root} == {"Books", "Loose"}

    inside = api.get(reverse("library:folders"), {"parent": books.pk}).json()
    assert {f["name"] for f in inside} == {"Fiction"}


@pytest.mark.django_db
def test_folder_detail_includes_breadcrumbs(api, user):
    books = Folder.objects.create(owner=user, name="Books")
    fiction = Folder.objects.create(owner=user, name="Fiction", parent=books)

    body = api.get(reverse("library:folder-detail", args=[fiction.pk])).json()
    assert [f["name"] for f in body["ancestors"]] == ["Books"]


# -- authorization ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_another_users_folder_is_invisible(api, other_user):
    theirs = Folder.objects.create(owner=other_user, name="Theirs")

    assert api.get(reverse("library:folder-detail", args=[theirs.pk])).status_code == 404
    renamed = patch(api, "library:folder-detail", {"name": "Mine"}, args=[theirs.pk])
    assert renamed.status_code == 404
    assert api.delete(reverse("library:folder-detail", args=[theirs.pk]),
                      headers=api.headers).status_code == 404
    assert Folder.objects.filter(pk=theirs.pk, name="Theirs").exists()


@pytest.mark.django_db
def test_a_folder_cannot_be_parented_to_another_users_folder(api, other_user):
    theirs = Folder.objects.create(owner=other_user, name="Theirs")
    assert post(api, "library:folders",
                {"name": "Mine", "parent": theirs.pk}).status_code == 400


@pytest.mark.django_db
def test_another_users_book_is_invisible(api, other_user):
    theirs = Book.objects.create(owner=other_user, title="Theirs")
    for name in ("library:book-detail", "library:book-content", "library:book-thumbnail"):
        assert api.get(reverse(name, args=[theirs.pk])).status_code == 404


@pytest.mark.django_db
def test_library_endpoints_require_authentication(client):
    from django.test import Client

    anon = Client()
    for name in ("library:folders", "library:books", "library:trash", "library:storage"):
        assert anon.get(reverse(name)).status_code == 403


# -- uploads ----------------------------------------------------------------------- #

@pytest.mark.django_db
def test_upload_a_pdf(api):
    response = upload(api, [pdf_file("DDIA.pdf")])
    assert response.status_code == 201
    body = response.json()
    assert len(body["imported"]) == 1
    assert body["imported"][0]["title"] == "DDIA"
    assert Book.objects.live().count() == 1


@pytest.mark.django_db
def test_upload_into_a_folder(api, user):
    folder = Folder.objects.create(owner=user, name="Books")
    upload(api, [pdf_file("Dune.pdf")], folder=folder.pk)
    assert Book.objects.get(title="Dune").folder_id == folder.pk


@pytest.mark.django_db
def test_upload_several_at_once(api):
    response = upload(api, [pdf_file("A.pdf"), pdf_file("B.pdf", pages=2)])
    assert len(response.json()["imported"]) == 2


@pytest.mark.django_db
def test_a_byte_identical_upload_is_skipped(api):
    """The answer chosen for retried imports: skip, and say so."""
    payload = make_pdf(pages=3)
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("A.pdf", payload)]}, headers=api.headers)
    response = api.post(reverse("library:upload"),
                        {"files": [SimpleUploadedFile("A.pdf", payload)]},
                        headers=api.headers)

    assert response.json()["duplicates"] == 1
    assert Book.objects.live().count() == 1


@pytest.mark.django_db
def test_the_same_file_in_two_folders_is_kept_twice(api, user):
    """Deduplication is about disk, not about the library."""
    payload = make_pdf(pages=1)
    a = Folder.objects.create(owner=user, name="A")
    b = Folder.objects.create(owner=user, name="B")

    for folder in (a, b):
        api.post(reverse("library:upload"),
                 {"files": [SimpleUploadedFile("Same.pdf", payload)], "folder": str(folder.pk)},
                 headers=api.headers)

    assert Book.objects.live().count() == 2
    storage = LibraryStorage()
    assert len(list(storage.root.rglob("*.pdf"))) == 1, "one file, two books"


@pytest.mark.django_db
def test_a_non_pdf_upload_is_refused(api):
    response = upload(api, [SimpleUploadedFile("evil.pdf", b"MZ\x90\x00 not a pdf")])
    assert response.json()["errors"]
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_an_oversized_upload_is_refused(api, settings):
    settings.MAX_UPLOAD_BYTES = 100
    response = upload(api, [pdf_file("Big.pdf", pages=5)])
    assert response.json()["errors"]
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_an_upload_is_refused_when_the_disk_is_nearly_full(api, settings):
    settings.MIN_FREE_DISK_BYTES = 10 ** 15
    assert upload(api, [pdf_file()]).status_code == 507


# -- ZIP uploads -------------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_zip_is_queued_rather_than_extracted_inline(api):
    response = upload(api, [SimpleUploadedFile("library.zip", library_zip())])

    assert response.status_code == 201
    batch = response.json()["batches"][0]
    assert batch["status"] == "pending"
    assert Book.objects.count() == 0, "extraction should wait for the worker"


@pytest.mark.django_db
def test_a_zip_import_rebuilds_the_folder_structure(api, user):
    upload(api, [SimpleUploadedFile("library.zip", library_zip())])
    process_zip_batch(UploadBatch.objects.get())

    assert {b.path for b in Book.objects.live()} == {
        "Books/Programming/Python/Fluent Python",
        "Books/Programming/Architecture/DDIA",
        "Books/Fiction/Dune",
    }
    assert Folder.objects.live().filter(name="Programming").count() == 1


@pytest.mark.django_db
def test_a_zip_import_lands_inside_the_chosen_folder(api, user):
    target = Folder.objects.create(owner=user, name="Imported")
    upload(api, [SimpleUploadedFile("library.zip", library_zip())], folder=target.pk)
    process_zip_batch(UploadBatch.objects.get())

    assert Book.objects.get(title="Dune").path == "Imported/Books/Fiction/Dune"


@pytest.mark.django_db
def test_reimporting_the_same_zip_changes_nothing(api):
    """Skip-duplicates makes a retried import idempotent."""
    for _ in range(2):
        upload(api, [SimpleUploadedFile("library.zip", library_zip())])
    batches = list(UploadBatch.objects.order_by("pk"))
    process_zip_batch(batches[0])
    process_zip_batch(batches[1])

    assert Book.objects.live().count() == 3
    assert batches[1].skipped_duplicate == 3
    assert Folder.objects.live().filter(name="Fiction").count() == 1


@pytest.mark.django_db
def test_one_bad_entry_does_not_lose_the_rest(api):
    payload = build_zip({
        "Books/Good.pdf": make_pdf(),
        "Books/Broken.pdf": b"%PDF- truncated",
        "Books/AlsoGood.pdf": make_pdf(pages=2),
    })
    upload(api, [SimpleUploadedFile("mixed.zip", payload)])
    batch = process_zip_batch(UploadBatch.objects.get())

    assert batch.imported == 3  # the truncated one still stores; probing flags it later
    assert Book.objects.live().count() == 3


@pytest.mark.django_db
def test_the_staged_archive_is_removed_after_import(api):
    """Keeping it would silently double the disk every import costs."""
    upload(api, [SimpleUploadedFile("library.zip", library_zip())])
    batch = UploadBatch.objects.get()
    staged = batch.staged_path
    assert staged

    process_zip_batch(batch)

    from pathlib import Path
    assert not Path(staged).exists()


@pytest.mark.django_db
def test_a_hostile_zip_imports_nothing_dangerous(api):
    payload = build_zip(
        {"../../escape.pdf": make_pdf(), "Books/fine.pdf": make_pdf()},
        symlinks={"Books/link.pdf": "/etc/passwd"},
    )
    upload(api, [SimpleUploadedFile("hostile.zip", payload)])
    batch = process_zip_batch(UploadBatch.objects.get())

    assert [b.title for b in Book.objects.live()] == ["fine"]
    assert batch.status == UploadBatch.Status.PARTIAL
    assert "unsafe path" in batch.error_summary


# -- content and processing ---------------------------------------------------------- #

@pytest.mark.django_db
def test_probing_fills_in_page_count_and_thumbnail(api):
    upload(api, [pdf_file("DDIA.pdf", pages=4)])
    result = process_pending_documents()

    assert result["processed"] == 1
    book = Book.objects.get()
    assert book.page_count == 4
    assert book.has_text_layer is True
    assert book.thumbnail_path


@pytest.mark.django_db
def test_content_is_streamed_to_the_owner(api):
    upload(api, [pdf_file("DDIA.pdf")])
    book = Book.objects.get()

    response = api.get(reverse("library:book-content", args=[book.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Accept-Ranges"] == "bytes"
    assert b"".join(response.streaming_content).startswith(b"%PDF-")


@pytest.mark.django_db
def test_a_missing_stored_file_reports_410_rather_than_crashing(api):
    upload(api, [pdf_file()])
    book = Book.objects.get()
    LibraryStorage().path_for(book.source.storage_key).unlink()

    assert api.get(reverse("library:book-content", args=[book.pk])).status_code == 410


# -- trash ------------------------------------------------------------------------- #

@pytest.mark.django_db
def test_deleting_a_book_moves_it_to_the_trash(api):
    upload(api, [pdf_file()])
    book = Book.objects.get()

    assert api.delete(reverse("library:book-detail", args=[book.pk]),
                      headers=api.headers).status_code == 204

    book.refresh_from_db()
    assert book.deleted_at is not None
    assert LibraryStorage().exists(book.source.storage_key), "the file was destroyed"


@pytest.mark.django_db
def test_a_trashed_book_is_hidden_but_restorable(api):
    upload(api, [pdf_file()])
    book = Book.objects.get()
    api.delete(reverse("library:book-detail", args=[book.pk]), headers=api.headers)

    assert api.get(reverse("library:books")).json() == []
    assert len(api.get(reverse("library:trash")).json()["books"]) == 1

    assert post(api, "library:book-restore", args=[book.pk]).status_code == 200
    assert len(api.get(reverse("library:books")).json()) == 1


@pytest.mark.django_db
def test_permanent_deletion_requires_the_trash_first(api):
    upload(api, [pdf_file()])
    book = Book.objects.get()

    response = api.delete(f"{reverse('library:book-detail', args=[book.pk])}?permanent=true",
                          headers=api.headers)

    assert response.status_code == 409
    assert Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_permanent_deletion_removes_the_file(api):
    upload(api, [pdf_file()])
    book = Book.objects.get()
    key = book.source.storage_key
    api.delete(reverse("library:book-detail", args=[book.pk]), headers=api.headers)

    api.delete(f"{reverse('library:book-detail', args=[book.pk])}?permanent=true",
               headers=api.headers)

    assert not Book.objects.filter(pk=book.pk).exists()
    assert not LibraryStorage().exists(key)


@pytest.mark.django_db
def test_trashing_a_folder_hides_its_books(api, user):
    folder = Folder.objects.create(owner=user, name="Books")
    upload(api, [pdf_file("A.pdf"), pdf_file("B.pdf", pages=2)], folder=folder.pk)

    response = api.delete(reverse("library:folder-detail", args=[folder.pk]),
                          headers=api.headers)

    assert response.json()["trashed"] == {"folders": 1, "books": 2}
    assert api.get(reverse("library:books")).json() == []
    assert post(api, "library:folder-restore", args=[folder.pk]).status_code == 200
    assert len(api.get(reverse("library:books")).json()) == 2


@pytest.mark.django_db
def test_a_batch_with_no_staged_file_fails_clearly(user):
    """An empty staged_path must not reach zipfile as the current directory."""
    batch = UploadBatch.objects.create(owner=user, original_filename="gone.zip",
                                       staged_path="")
    process_zip_batch(batch)

    assert batch.status == UploadBatch.Status.FAILED
    assert "no longer on disk" in batch.error_summary
    assert "Is a directory" not in batch.error_summary
