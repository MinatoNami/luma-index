"""The object-level permission matrix PRD §29 requires.

Three users against a private and a shared book, across every book-scoped
endpoint. Built as a matrix rather than a pile of individual tests so a gap is
visible as a missing row instead of an absent file.

Two of the expectations are deliberate and worth stating:

* **404, not 403, for a book you may not see.** A 403 confirms the book exists,
  which is itself a disclosure.
* **An admin gets nothing extra.** PRD §8: "Admin status should not
  automatically expose private user annotations through the normal application
  UI." Instance management happens in Django Admin, which is a separate and
  audited path.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from library.models import Book, Folder
from library.services import process_pending_documents

from .pdfs import make_pdf

User = get_user_model()
PASSWORD = "a-long-enough-password-42"
QUADS = {"v": 1, "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]}


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.headers = {"x-csrftoken": client.cookies["lumaindex_csrftoken"].value}
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def stranger(db):
    return User.objects.create_user(email="stranger@example.com", password=PASSWORD)


@pytest.fixture
def admin(db):
    return User.objects.create_superuser(email="admin@example.com", password=PASSWORD)


@pytest.fixture
def books(owner):
    """One private and one shared book, both with real content.

    The two PDFs differ deliberately. Identical bytes would deduplicate to a
    single stored file and the second upload would be skipped — the storage
    layer behaving correctly, and a fixture that silently produces one book.
    """
    client = signed_in(owner)
    made = {}
    for index, (name, visibility) in enumerate((("private", Book.Visibility.PRIVATE),
                                                ("shared", Book.Visibility.SHARED))):
        client.post(
            reverse("library:upload"),
            {"files": [SimpleUploadedFile(f"{name}.pdf",
                                          make_pdf(pages=4 + index, text=f"{name} book"))]},
            headers=client.headers,
        )
        book = Book.objects.exclude(pk__in=[b.pk for b in made.values()]).get()
        book.visibility = visibility
        book.save(update_fields=["visibility"])
        made[name] = book
    process_pending_documents()
    return made


# (label, method, url name, payload)
READ_ENDPOINTS = [
    ("detail", "get", "library:book-detail", None),
    ("content", "get", "library:book-content", None),
    ("thumbnail", "get", "library:book-thumbnail", None),
    ("outline", "get", "library:book-outline", None),
    ("progress", "get", "library:book-progress", None),
    ("bookmarks", "get", "library:bookmarks", None),
    ("highlights", "get", "library:highlights", None),
    ("notes", "get", "library:notes", None),
]

WRITE_ENDPOINTS = [
    ("rename", "patch", "library:book-detail", {"title": "Taken"}),
    ("trash", "delete", "library:book-detail", None),
    ("share", "post", "library:book-share", {"visibility": "private"}),
]

ANNOTATE_ENDPOINTS = [
    ("add bookmark", "post", "library:bookmarks", {"page": 1}),
    ("add highlight", "post", "library:highlights", {"page": 0, "position_data": QUADS}),
    ("add note", "post", "library:notes", {"page": 0, "body": "mine"}),
    ("set progress", "put", "library:book-progress", {"page": 1, "page_fraction": 0.0}),
]


def call(client, method, name, book, payload):
    url = reverse(name, args=[book.pk])
    if method == "get":
        return client.get(url)
    if method == "delete":
        return client.delete(url, headers=client.headers)
    return getattr(client, method)(url, payload or {}, content_type="application/json",
                                   headers=client.headers)


# -- reading ------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", READ_ENDPOINTS)
def test_owner_may_read_their_private_book(owner, books, label, method, name, payload):
    assert call(signed_in(owner), method, name, books["private"], payload).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", READ_ENDPOINTS)
def test_a_stranger_cannot_read_a_private_book(stranger, books, label, method, name, payload):
    response = call(signed_in(stranger), method, name, books["private"], payload)
    assert response.status_code == 404, f"{label} leaked a private book"


@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", READ_ENDPOINTS)
def test_an_admin_gets_no_extra_read_access(admin, books, label, method, name, payload):
    """PRD §8. Admins manage the instance through Django Admin, not by being
    able to open everyone's private books in the reader."""
    response = call(signed_in(admin), method, name, books["private"], payload)
    assert response.status_code == 404, f"{label} exposed a private book to an admin"


@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", READ_ENDPOINTS)
def test_a_stranger_may_read_a_shared_book(stranger, books, label, method, name, payload):
    assert call(signed_in(stranger), method, name, books["shared"], payload).status_code == 200


# -- writing -------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", WRITE_ENDPOINTS)
def test_a_stranger_cannot_modify_a_shared_book(stranger, books, label, method, name, payload):
    """Readable is not writable: sharing grants reading, nothing else."""
    response = call(signed_in(stranger), method, name, books["shared"], payload)
    assert response.status_code == 404, f"{label} let a reader modify someone else's book"

    books["shared"].refresh_from_db()
    assert books["shared"].title != "Taken"
    assert books["shared"].deleted_at is None
    assert books["shared"].visibility == Book.Visibility.SHARED


@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", WRITE_ENDPOINTS)
def test_an_admin_cannot_modify_someone_elses_book(admin, books, label, method, name, payload):
    response = call(signed_in(admin), method, name, books["shared"], payload)
    assert response.status_code == 404, f"{label} let an admin modify another user's book"


# -- annotating ------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", ANNOTATE_ENDPOINTS)
def test_a_reader_may_annotate_a_shared_book(stranger, books, label, method, name, payload):
    """Their own annotations on someone else's book — that is the point of §19."""
    response = call(signed_in(stranger), method, name, books["shared"], payload)
    assert response.status_code in (200, 201), f"{label} refused a legitimate reader"


@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload", ANNOTATE_ENDPOINTS)
def test_nobody_may_annotate_a_book_they_cannot_read(stranger, books, label, method,
                                                     name, payload):
    response = call(signed_in(stranger), method, name, books["private"], payload)
    assert response.status_code == 404, f"{label} accepted a write on an unreadable book"


# -- anonymous --------------------------------------------------------------------- #

@pytest.mark.django_db
@pytest.mark.parametrize("label,method,name,payload",
                         READ_ENDPOINTS + WRITE_ENDPOINTS + ANNOTATE_ENDPOINTS)
def test_anonymous_access_is_refused_everywhere(books, label, method, name, payload):
    anonymous = Client()
    anonymous.headers = {}
    response = call(anonymous, method, name, books["shared"], payload)
    assert response.status_code in (403, 404), f"{label} served an anonymous request"


# -- folders ------------------------------------------------------------------------ #

@pytest.mark.django_db
def test_folders_are_never_visible_across_users(owner, stranger, admin):
    folder = Folder.objects.create(owner=owner, name="Private Folder")

    for user, who in ((stranger, "a stranger"), (admin, "an admin")):
        client = signed_in(user)
        assert client.get(reverse("library:folder-detail",
                                  args=[folder.pk])).status_code == 404, who
        assert client.patch(reverse("library:folder-detail", args=[folder.pk]),
                            {"name": "Theirs"}, content_type="application/json",
                            headers=client.headers).status_code == 404, who
        assert client.delete(reverse("library:folder-detail", args=[folder.pk]),
                             headers=client.headers).status_code == 404, who

    folder.refresh_from_db()
    assert folder.name == "Private Folder" and folder.deleted_at is None


@pytest.mark.django_db
def test_a_users_library_listing_never_includes_another_users_books(owner, stranger, books):
    listed = signed_in(stranger).get(reverse("library:books")).json()
    assert listed == [], "the library listing leaked another user's books"


@pytest.mark.django_db
def test_trash_only_ever_shows_your_own(owner, stranger, books):
    books["private"].trash()

    body = signed_in(stranger).get(reverse("library:trash")).json()

    # The lists, not the whole envelope: the trash also reports the instance's
    # retention policy, which is not somebody else's data.
    assert (body["folders"], body["books"]) == ([], [])
