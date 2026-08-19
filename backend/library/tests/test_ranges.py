"""Byte-range responses.

The endpoint used to advertise `Accept-Ranges: bytes` and then ignore every
range it was sent, which is worse than staying silent — a client that trusts the
header gets the whole file. PDF.js reads a PDF's trailer from the end before
anything else, so without 206 a large book downloads in full before page one
renders.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from library.models import Book
from library.ranges import parse_range

from .pdfs import make_pdf


@pytest.fixture
def book(api):
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Book.pdf", make_pdf(pages=6))]},
             headers=api.headers)
    return Book.objects.get()


def body_of(response) -> bytes:
    return b"".join(response.streaming_content)


# -- header parsing ------------------------------------------------------------ #

@pytest.mark.parametrize("header,size,expected", [
    ("bytes=0-99", 1000, (0, 99)),
    ("bytes=100-199", 1000, (100, 199)),
    ("bytes=900-", 1000, (900, 999)),
    ("bytes=0-", 1000, (0, 999)),
    # A suffix range — how PDF.js asks for the trailer.
    ("bytes=-100", 1000, (900, 999)),
    # Clamped rather than rejected: asking past the end is normal.
    ("bytes=0-99999", 1000, (0, 999)),
    ("", 1000, None),
    ("bytes=-", 1000, None),
    # Multi-range: permitted to answer with the whole file, which every
    # client handles, rather than half-implement multipart/byteranges.
    ("bytes=0-49,100-149", 1000, None),
    ("rubbish", 1000, None),
])
def test_range_headers_parse(header, size, expected):
    assert parse_range(header, size) == expected


@pytest.mark.parametrize("header,size", [("bytes=1000-", 1000), ("bytes=5000-6000", 1000),
                                         ("bytes=-0", 1000)])
def test_unsatisfiable_ranges_are_flagged(header, size):
    assert parse_range(header, size) == "invalid"


# -- responses ----------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_plain_request_returns_the_whole_file(api, book):
    response = api.get(reverse("library:book-content", args=[book.pk]))
    assert response.status_code == 200
    assert response["Accept-Ranges"] == "bytes"
    assert body_of(response).startswith(b"%PDF-")


@pytest.mark.django_db
def test_a_range_request_returns_206_with_only_those_bytes(api, book):
    whole = body_of(api.get(reverse("library:book-content", args=[book.pk])))

    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=10-29"})

    assert response.status_code == 206
    assert response["Content-Range"] == f"bytes 10-29/{len(whole)}"
    assert response["Content-Length"] == "20"
    assert body_of(response) == whole[10:30]


@pytest.mark.django_db
def test_a_suffix_range_returns_the_tail(api, book):
    """This is the request PDF.js makes first, to find the trailer."""
    whole = body_of(api.get(reverse("library:book-content", args=[book.pk])))

    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=-40"})

    assert response.status_code == 206
    # Read once: streaming_content is an iterator, and a second pass sees
    # nothing — which is how this test first "passed" against an empty body.
    tail = body_of(response)
    assert tail == whole[-40:]
    assert b"%%EOF" in tail


@pytest.mark.django_db
def test_an_open_ended_range_runs_to_the_end(api, book):
    whole = body_of(api.get(reverse("library:book-content", args=[book.pk])))
    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=100-"})
    assert response.status_code == 206
    assert body_of(response) == whole[100:]


@pytest.mark.django_db
def test_a_range_past_the_end_is_clamped(api, book):
    whole = body_of(api.get(reverse("library:book-content", args=[book.pk])))
    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=0-999999"})
    assert response.status_code == 206
    assert body_of(response) == whole


@pytest.mark.django_db
def test_an_unsatisfiable_range_returns_416(api, book):
    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=999999-"})
    assert response.status_code == 416
    assert response["Content-Range"].startswith("bytes */")


@pytest.mark.django_db
def test_content_can_be_framed_by_our_own_pages_only(api, book):
    """DENY globally is right for the app, but it also blocks our own reader."""
    response = api.get(reverse("library:book-content", args=[book.pk]))
    assert response["X-Frame-Options"] == "SAMEORIGIN"

    # Everything else stays un-framable.
    assert api.get(reverse("library:books"))["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
def test_a_quote_in_a_filename_cannot_break_the_header(api, user):
    from library.models import BookSource
    from library.storage import LibraryStorage

    blob = LibraryStorage().store_stream(iter([make_pdf(pages=1)]))
    created = Book.objects.create(owner=user, title="Odd")
    BookSource.objects.create(book=created, storage_key=blob.storage_key,
                              original_filename='we"ird\\name.pdf', file_size=blob.size)

    response = api.get(reverse("library:book-content", args=[created.pk]))
    disposition = response["Content-Disposition"]
    assert disposition.count('"') == 2, disposition


@pytest.mark.django_db
def test_ranges_still_require_authorization(client, book, other_user):
    """A range request is not a way around the permission check."""
    from django.test import Client

    intruder = Client()
    intruder.force_login(other_user)
    response = intruder.get(reverse("library:book-content", args=[book.pk]),
                            headers={"range": "bytes=0-9"})
    assert response.status_code == 404


# -- not downloading the same book twice --------------------------------------- #

@pytest.mark.django_db
def test_the_content_response_carries_the_files_own_hash(api, book):
    """Content addressing makes an exact validator free: the storage key is the
    SHA-256 of the bytes, so it cannot claim "unchanged" about a changed file."""
    response = api.get(reverse("library:book-content", args=[book.pk]))

    assert response["ETag"] == f'"{book.source.storage_key}"'
    assert "max-age" in response["Cache-Control"]
    assert "private" in response["Cache-Control"], "Django authorised this; no shared cache"


@pytest.mark.django_db
def test_a_second_request_costs_a_304_not_the_whole_book(api, book):
    first = api.get(reverse("library:book-content", args=[book.pk]))

    again = api.get(reverse("library:book-content", args=[book.pk]),
                    headers={"if-none-match": first["ETag"]})

    assert again.status_code == 304
    assert again["ETag"] == first["ETag"]


@pytest.mark.django_db
def test_a_stale_validator_still_gets_the_file(api, book):
    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"if-none-match": '"not-the-current-hash"'})

    assert response.status_code == 200
    assert body_of(response).startswith(b"%PDF-")


@pytest.mark.django_db
def test_a_range_resumes_when_the_file_has_not_changed(api, book):
    """A matching If-Range means the client may stitch these bytes onto what it
    already has."""
    etag = api.get(reverse("library:book-content", args=[book.pk]))["ETag"]

    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=0-99", "if-range": etag})

    assert response.status_code == 206
    assert response["Content-Range"].startswith("bytes 0-99/")


@pytest.mark.django_db
def test_a_range_against_a_version_we_no_longer_have_is_answered_in_full(api, book):
    """Otherwise the client stitches new bytes onto an old prefix and ends up
    with a file that is neither."""
    response = api.get(reverse("library:book-content", args=[book.pk]),
                       headers={"range": "bytes=0-99", "if-range": '"an-older-hash"'})

    assert response.status_code == 200
    assert "Content-Range" not in response
