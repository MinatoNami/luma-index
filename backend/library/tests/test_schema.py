"""The published schema has to match what the endpoints actually return.

PRD §45 counts a published OpenAPI schema as a criterion, which makes a wrong
one worse than none: it is believed. Adding pagination changed six endpoints
from a bare array to an envelope and left every `responses=` decorator claiming
the old shape — nothing failed, because nothing compared them.

This is that comparison. It is deliberately about the *shape* rather than every
field: the point is to catch a response that grew or lost a top-level key
without its declaration moving.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator

from library.models import Book, BookSource, Collection, CollectionBook, Folder

User = get_user_model()
PASSWORD = "a-long-enough-password-42"


@pytest.fixture
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


@pytest.fixture
def reader(db):
    user = User.objects.create_user(email="reader@example.com", password=PASSWORD)
    folder = Folder.objects.create(owner=user, name="Shelf")
    book = Book.objects.create(owner=user, folder=folder, title="A Book")
    BookSource.objects.create(book=book, storage_key=f"{book.pk:064d}",
                              original_filename="a-book.pdf", file_size=2048)
    collection = Collection.objects.create(owner=user, name="A Collection")
    CollectionBook.objects.create(collection=collection, book=book)
    return user, collection


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    return client


def declared_keys(schema: dict, path: str) -> set[str]:
    """Top-level properties the schema says a 200 from `path` carries."""
    operation = schema["paths"][path]["get"]
    content = operation["responses"]["200"]["content"]["application/json"]["schema"]
    ref = content.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        content = schema["components"]["schemas"][name]
    return set(content.get("properties", {}))


PAGINATED = [
    ("library:books", ()),
    ("library:folders", ()),
    ("library:shared", ()),
    ("library:collections", ()),
    ("library:notebook", ()),
]


@pytest.mark.django_db
@pytest.mark.parametrize("name,args", PAGINATED)
def test_the_schema_describes_what_the_endpoint_returns(schema, reader, name, args):
    user, _ = reader
    path = reverse(name, args=args)

    body = signed_in(user).get(path).json()
    assert isinstance(body, dict), f"{name} returned a bare array"

    assert declared_keys(schema, path) == set(body), (
        f"{name}: the schema and the response disagree about the top-level keys"
    )


@pytest.mark.django_db
def test_the_collection_books_schema_matches_too(schema, reader):
    user, collection = reader
    path = reverse("library:collection-books", args=[collection.pk])
    body = signed_in(user).get(path).json()

    # The path is templated in the schema, not the concrete id.
    declared = declared_keys(schema, "/api/library/collections/{collection_id}/books/")
    assert declared == set(body)


@pytest.mark.django_db
@pytest.mark.parametrize("name,args", PAGINATED)
def test_limit_and_offset_are_documented(schema, name, args):
    """They are how a client reaches anything past the first page, so a client
    reading the schema has to be able to find them."""
    operation = schema["paths"][reverse(name, args=args)]["get"]
    documented = {p["name"] for p in operation.get("parameters", [])}
    assert {"limit", "offset"} <= documented, f"{name} does not document paging"


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["library:activity", "library:notebook-daily"])
def test_the_activity_and_daily_schemas_match_too(schema, reader, name):
    user, _ = reader
    path = reverse(name)
    body = signed_in(user).get(path).json()
    assert declared_keys(schema, path) == set(body)
