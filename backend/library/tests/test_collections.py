"""Collections and favourites — the second half of PRD §12.

Folders are where a file lives; collections are how a reader thinks about it,
and the same book belongs to several at once without the file being duplicated.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from library.models import Book, Collection, CollectionBook, UserBookState

from .pdfs import make_pdf


@pytest.fixture
def book(api):
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Book.pdf", make_pdf(pages=3))]},
             headers=api.headers)
    return Book.objects.get()


def post(client, name, payload=None, args=None):
    return client.post(reverse(name, args=args or []), payload or {},
                       content_type="application/json", headers=client.headers)


# -- collections ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_create_and_list_a_collection(api):
    assert post(api, "library:collections", {"name": "Currently Reading"}).status_code == 201
    listed = api.get(reverse("library:collections")).json()
    assert [c["name"] for c in listed] == ["Currently Reading"]


@pytest.mark.django_db
def test_collections_nest(api, user):
    parent = Collection.objects.create(owner=user, name="Technical")
    response = post(api, "library:collections", {"name": "Databases", "parent": parent.pk})
    assert response.json()["path"] == "Technical/Databases"


@pytest.mark.django_db
def test_duplicate_names_are_refused_at_each_level(api, user):
    Collection.objects.create(owner=user, name="Fiction")
    assert post(api, "library:collections", {"name": "Fiction"}).status_code == 409


@pytest.mark.django_db
def test_a_collection_cannot_be_moved_inside_itself(api, user):
    outer = Collection.objects.create(owner=user, name="Outer")
    inner = Collection.objects.create(owner=user, name="Inner", parent=outer)

    response = api.patch(reverse("library:collection-detail", args=[outer.pk]),
                         {"parent": inner.pk}, content_type="application/json",
                         headers=api.headers)
    assert response.status_code == 400
    outer.refresh_from_db()
    assert outer.parent_id is None


@pytest.mark.django_db
def test_one_book_can_be_in_several_collections(api, user, book):
    """PRD §11: the same book in three collections is one file."""
    names = ["Currently Reading", "Software", "Favourites-ish"]
    for name in names:
        collection = Collection.objects.create(owner=user, name=name)
        post(api, "library:collection-books", {"book_id": book.pk}, args=[collection.pk])

    assert CollectionBook.objects.filter(book=book).count() == 3
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_removing_a_book_from_a_collection_keeps_the_book(api, user, book):
    collection = Collection.objects.create(owner=user, name="Temp")
    post(api, "library:collection-books", {"book_id": book.pk}, args=[collection.pk])

    api.delete(reverse("library:collection-book-detail", args=[collection.pk, book.pk]),
               headers=api.headers)

    assert not CollectionBook.objects.filter(book=book).exists()
    assert Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_deleting_a_collection_keeps_its_books(api, user, book):
    """A collection is a view onto a library, not a container that owns anything."""
    collection = Collection.objects.create(owner=user, name="Doomed")
    post(api, "library:collection-books", {"book_id": book.pk}, args=[collection.pk])

    api.delete(reverse("library:collection-detail", args=[collection.pk]),
               headers=api.headers)

    assert not Collection.objects.filter(pk=collection.pk).exists()
    assert Book.objects.live().filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_a_book_can_be_in_a_collection_and_a_folder_independently(api, user, book):
    """§11: reorganising one never moves the other."""
    from library.models import Folder

    folder = Folder.objects.create(owner=user, name="Somewhere")
    book.folder = folder
    book.save(update_fields=["folder"])
    collection = Collection.objects.create(owner=user, name="Reading")
    post(api, "library:collection-books", {"book_id": book.pk}, args=[collection.pk])

    api.delete(reverse("library:collection-book-detail", args=[collection.pk, book.pk]),
               headers=api.headers)

    book.refresh_from_db()
    assert book.folder_id == folder.pk, "leaving a collection moved the file"


@pytest.mark.django_db
def test_collections_are_private(api, other_user, user):
    theirs = Collection.objects.create(owner=other_user, name="Theirs")

    assert api.get(reverse("library:collection-detail", args=[theirs.pk])).status_code == 404
    assert api.get(reverse("library:collections")).json() == []
    response = api.patch(reverse("library:collection-detail", args=[theirs.pk]),
                         {"name": "Mine"}, content_type="application/json",
                         headers=api.headers)
    assert response.status_code == 404


@pytest.mark.django_db
def test_a_collection_cannot_be_parented_to_another_users(api, other_user):
    theirs = Collection.objects.create(owner=other_user, name="Theirs")
    assert post(api, "library:collections",
                {"name": "Mine", "parent": theirs.pk}).status_code == 400


# -- favourites ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_favouriting_and_unfavouriting(api, book):
    assert post(api, "library:book-favourite", args=[book.pk]).status_code == 200
    assert UserBookState.objects.get(book=book).is_favourite is True

    api.delete(reverse("library:book-favourite", args=[book.pk]), headers=api.headers)
    assert UserBookState.objects.get(book=book).is_favourite is False


@pytest.mark.django_db
def test_favouriting_does_not_make_a_book_look_started(api, book):
    """Why this is not stored on ReadingProgress: a favourite you have never
    opened must not appear in Continue Reading."""
    post(api, "library:book-favourite", args=[book.pk])

    from library.models import ReadingProgress
    assert not ReadingProgress.objects.filter(book=book).exists()
    assert api.get(reverse("library:continue-reading")).json() == []


@pytest.mark.django_db
def test_favourites_are_per_reader(api, book, user, other_user):
    """A shared book favourited by one reader is not favourited for everyone."""
    book.visibility = Book.Visibility.SHARED
    book.save(update_fields=["visibility"])
    post(api, "library:book-favourite", args=[book.pk])

    reader = Client()
    reader.force_login(other_user)
    listed = reader.get(reverse("library:shared")).json()
    assert listed, "the shared book should be visible to the other reader"
    assert UserBookState.objects.filter(user=other_user).count() == 0


@pytest.mark.django_db
def test_the_favourites_view_lists_only_favourites(api, user):
    from library.models import BookSource

    for index in range(3):
        created = Book.objects.create(owner=user, title=f"Book {index}")
        BookSource.objects.create(book=created, storage_key=f"{index:064d}",
                                  original_filename=f"{index}.pdf", file_size=1)
        if index == 1:
            post(api, "library:book-favourite", args=[created.pk])

    listed = api.get(reverse("library:books"), {"view": "favourites"}).json()
    assert [b["title"] for b in listed] == ["Book 1"]
    assert listed[0]["is_favourite"] is True


@pytest.mark.django_db
def test_the_unsorted_view_lists_books_in_no_collection(api, user, book):
    from library.models import BookSource

    filed = Book.objects.create(owner=user, title="Filed")
    BookSource.objects.create(book=filed, storage_key="f" * 64,
                              original_filename="f.pdf", file_size=1)
    collection = Collection.objects.create(owner=user, name="Somewhere")
    post(api, "library:collection-books", {"book_id": filed.pk}, args=[collection.pk])

    listed = api.get(reverse("library:books"), {"view": "unsorted"}).json()
    titles = [b["title"] for b in listed]
    assert book.title in titles
    assert "Filed" not in titles


@pytest.mark.django_db
def test_filtering_by_collection(api, user, book):
    collection = Collection.objects.create(owner=user, name="Reading")
    post(api, "library:collection-books", {"book_id": book.pk}, args=[collection.pk])

    listed = api.get(reverse("library:books"), {"collection": collection.pk}).json()
    assert [b["id"] for b in listed] == [book.pk]


@pytest.mark.django_db
def test_another_users_collection_cannot_be_filtered_by(api, other_user, book):
    theirs = Collection.objects.create(owner=other_user, name="Theirs")
    CollectionBook.objects.create(collection=theirs, book=book)

    assert api.get(reverse("library:books"), {"collection": theirs.pk}).json() == []


@pytest.mark.django_db
def test_listing_favourites_does_not_query_per_book(api, user, django_assert_max_num_queries):
    from library.models import BookSource

    for index in range(15):
        created = Book.objects.create(owner=user, title=f"Book {index}")
        BookSource.objects.create(book=created, storage_key=f"{index:064d}",
                                  original_filename=f"{index}.pdf", file_size=1)
        UserBookState.objects.create(user=user, book=created, is_favourite=True)

    with django_assert_max_num_queries(10):
        listed = api.get(reverse("library:books")).json()
    assert len(listed) == 15
    assert all(b["is_favourite"] for b in listed)
