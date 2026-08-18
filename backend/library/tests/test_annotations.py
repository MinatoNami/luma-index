"""Bookmarks, highlights, and page notes.

PRD §19 and §24 make these per-user and private; §23 requires positions that
survive a zoom change. The tests that matter most are the ones asserting one
reader cannot see or touch another's.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from library.annotations import CURRENT_VERSION, validate_position_data
from library.models import Book, Bookmark, Highlight, PageNote

from .pdfs import make_pdf


@pytest.fixture
def book(api):
    api.post(reverse("library:upload"),
             {"files": [SimpleUploadedFile("Book.pdf", make_pdf(pages=10))]},
             headers=api.headers)
    return Book.objects.get()


def quads(*boxes):
    return {"v": CURRENT_VERSION,
            "quads": [{"x1": a, "y1": b, "x2": c, "y2": d} for a, b, c, d in boxes]}


def post(client, name, book, payload):
    return client.post(reverse(name, args=[book.pk]), payload,
                       content_type="application/json", headers=client.headers)


# -- anchor validation ---------------------------------------------------------- #

def test_a_valid_anchor_is_normalised():
    result = validate_position_data(quads((10, 20, 30, 40)))
    assert result["v"] == CURRENT_VERSION
    assert result["quads"] == [{"x1": 10.0, "y1": 20.0, "x2": 30.0, "y2": 40.0}]


@pytest.mark.parametrize("bad", [
    "not an object",
    {"v": 1, "quads": []},
    {"v": 1, "quads": "nope"},
    {"v": 1, "quads": [{"x1": 1, "y1": 2, "x2": 3}]},
    {"v": 1, "quads": [{"x1": "a", "y1": 2, "x2": 3, "y2": 4}]},
    {"v": 1, "quads": [{"x1": True, "y1": 2, "x2": 3, "y2": 4}]},
    {"v": 1, "quads": [{"x1": 1e9, "y1": 2, "x2": 3, "y2": 4}]},
])
def test_malformed_anchors_are_refused(bad):
    """Stored once and read back for years, so it is validated, not trusted."""
    from rest_framework import serializers

    with pytest.raises(serializers.ValidationError):
        validate_position_data(bad)


def test_a_future_version_is_refused():
    from rest_framework import serializers

    with pytest.raises(serializers.ValidationError, match="Unsupported"):
        validate_position_data({"v": 99, "quads": [{"x1": 1, "y1": 1, "x2": 2, "y2": 2}]})


def test_text_offsets_are_kept_when_sane():
    result = validate_position_data({**quads((1, 1, 2, 2)),
                                     "text_offsets": {"start": 10, "end": 20}})
    assert result["text_offsets"] == {"start": 10, "end": 20}


def test_nonsense_offsets_are_dropped_rather_than_rejected():
    """A bad secondary anchor should not lose the highlight itself."""
    result = validate_position_data({**quads((1, 1, 2, 2)),
                                     "text_offsets": {"start": 50, "end": 10}})
    assert "text_offsets" not in result


# -- bookmarks -------------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_bookmark_round_trips(api, book):
    response = post(api, "library:bookmarks", book, {"page": 4, "label": "The good bit"})
    assert response.status_code == 201

    listed = api.get(reverse("library:bookmarks", args=[book.pk])).json()
    assert [b["label"] for b in listed] == ["The good bit"]


@pytest.mark.django_db
def test_a_page_can_only_be_bookmarked_once(api, book):
    post(api, "library:bookmarks", book, {"page": 4})
    assert post(api, "library:bookmarks", book, {"page": 4}).status_code == 409


@pytest.mark.django_db
def test_a_bookmark_can_be_renamed_and_removed(api, book):
    created = post(api, "library:bookmarks", book, {"page": 2, "label": "x"}).json()

    api.patch(reverse("library:bookmark-detail", args=[book.pk, created["id"]]),
              {"label": "Chapter 3"}, content_type="application/json", headers=api.headers)
    assert Bookmark.objects.get().label == "Chapter 3"

    api.delete(reverse("library:bookmark-detail", args=[book.pk, created["id"]]),
               headers=api.headers)
    assert not Bookmark.objects.exists()


# -- highlights ------------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_highlight_round_trips(api, book):
    response = post(api, "library:highlights", book, {
        "page": 3, "selected_text": "a passage",
        "position_data": quads((72, 640, 288, 652)), "colour": "green",
    })
    assert response.status_code == 201
    stored = Highlight.objects.get()
    assert stored.colour == "green"
    assert stored.position_data["quads"][0]["x1"] == 72.0


@pytest.mark.django_db
def test_a_multi_line_highlight_keeps_every_rectangle(api, book):
    """A selection spanning three lines is three quads; one box would cover the
    margins between them."""
    post(api, "library:highlights", book, {
        "page": 1, "selected_text": "three lines",
        "position_data": quads((72, 700, 500, 712), (72, 686, 500, 698), (72, 672, 300, 684)),
    })
    assert len(Highlight.objects.get().position_data["quads"]) == 3


@pytest.mark.django_db
def test_a_malformed_highlight_is_rejected(api, book):
    response = post(api, "library:highlights", book, {
        "page": 1, "position_data": {"v": 1, "quads": [{"x1": "oops"}]},
    })
    assert response.status_code == 400
    assert not Highlight.objects.exists()


@pytest.mark.django_db
def test_a_note_can_be_attached_to_a_highlight(api, book):
    created = post(api, "library:highlights", book, {
        "page": 1, "position_data": quads((1, 1, 2, 2)),
    }).json()

    api.patch(reverse("library:highlight-detail", args=[book.pk, created["id"]]),
              {"note": "Worth revisiting"}, content_type="application/json",
              headers=api.headers)
    assert Highlight.objects.get().note == "Worth revisiting"


@pytest.mark.django_db
def test_highlights_can_be_fetched_for_one_page(api, book):
    for page in (1, 1, 5):
        post(api, "library:highlights", book,
             {"page": page, "position_data": quads((1, 1, 2, 2))})

    listed = api.get(reverse("library:highlights", args=[book.pk]), {"page": 1}).json()
    assert len(listed) == 2


# -- page notes -------------------------------------------------------------------- #

@pytest.mark.django_db
def test_a_page_note_round_trips(api, book):
    """The route that works on a scan, where there is no text to anchor to."""
    response = post(api, "library:notes", book, {"page": 7, "body": "  Diagram is wrong  "})
    assert response.status_code == 201
    assert PageNote.objects.get().body == "Diagram is wrong"


@pytest.mark.django_db
def test_an_empty_note_is_refused(api, book):
    assert post(api, "library:notes", book, {"page": 1, "body": "   "}).status_code == 400


# -- privacy ------------------------------------------------------------------------ #

@pytest.mark.django_db
def test_annotations_are_invisible_to_another_reader(api, book, other_user):
    """PRD §24: no access to another user's private annotations."""
    post(api, "library:highlights", book, {"page": 1, "position_data": quads((1, 1, 2, 2))})
    post(api, "library:bookmarks", book, {"page": 1})
    post(api, "library:notes", book, {"page": 1, "body": "mine"})

    intruder = Client()
    intruder.force_login(other_user)
    for name in ("library:highlights", "library:bookmarks", "library:notes"):
        # 404 rather than an empty list: they cannot see the book either.
        assert intruder.get(reverse(name, args=[book.pk])).status_code == 404


@pytest.mark.django_db
def test_one_reader_cannot_edit_anothers_annotation(api, book, other_user, user):
    created = post(api, "library:highlights", book,
                   {"page": 1, "position_data": quads((1, 1, 2, 2))}).json()

    # Give the intruder their own book so the URL resolves for them.
    theirs = Book.objects.create(owner=other_user, title="Theirs")
    intruder = Client()
    intruder.force_login(other_user)
    intruder.get(reverse("accounts:csrf"))
    headers = {"x-csrftoken": intruder.cookies["lumaindex_csrftoken"].value}

    response = intruder.patch(
        reverse("library:highlight-detail", args=[theirs.pk, created["id"]]),
        {"note": "hijacked"}, content_type="application/json", headers=headers)

    assert response.status_code == 404
    assert Highlight.objects.get().note == ""


@pytest.mark.django_db
def test_annotations_survive_their_file_going_missing(api, book):
    """PRD §13: a source becoming unavailable must not destroy reading data."""
    from library.models import BookSource

    post(api, "library:highlights", book, {"page": 1, "position_data": quads((1, 1, 2, 2))})
    post(api, "library:bookmarks", book, {"page": 1})

    BookSource.objects.filter(book=book).update(
        availability_status=BookSource.Availability.MISSING)

    assert Highlight.objects.filter(book=book).exists()
    assert Bookmark.objects.filter(book=book).exists()


@pytest.mark.django_db
def test_annotations_require_authentication(book):
    anon = Client()
    for name in ("library:highlights", "library:bookmarks", "library:notes"):
        assert anon.get(reverse(name, args=[book.pk])).status_code == 403
