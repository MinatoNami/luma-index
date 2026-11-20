"""The notebook: every highlight and page note, across books.

The tests that matter most are the ones about whose notes come back. The
per-book endpoints answer that with two checks on every request; the notebook
answers it once for a whole library, which is a bigger thing to get wrong.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from library import notebook
from library.models import Book, Bookmark, BookSource, Highlight, PageNote

QUAD = {"v": 1, "quads": [{"x1": 1.0, "y1": 1.0, "x2": 2.0, "y2": 2.0}]}


def make_book(owner, title: str, *, shared: bool = False) -> Book:
    book = Book.objects.create(
        owner=owner, title=title, page_count=50,
        visibility=Book.Visibility.SHARED if shared else Book.Visibility.PRIVATE,
    )
    BookSource.objects.create(book=book, storage_key=f"{book.pk:064d}",
                              original_filename=f"{title}.pdf", file_size=1024)
    return book


def highlight(user, book, page: int, text: str, *, note: str = "", colour: str = "yellow",
              ago: int = 0) -> Highlight:
    mark = Highlight.objects.create(user=user, book=book, page=page, selected_text=text,
                                    note=note, colour=colour, position_data=QUAD)
    # created_at is auto_now_add, so order is set afterwards to be exact about it.
    Highlight.objects.filter(pk=mark.pk).update(
        created_at=timezone.now() - timedelta(minutes=ago))
    return mark


def page_note(user, book, page: int, body: str, *, ago: int = 0) -> PageNote:
    note = PageNote.objects.create(user=user, book=book, page=page, body=body)
    PageNote.objects.filter(pk=note.pk).update(
        created_at=timezone.now() - timedelta(minutes=ago))
    return note


def listing(client, **params) -> dict:
    response = client.get(reverse("library:notebook"), params)
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def reader(other_user) -> Client:
    client = Client()
    client.force_login(other_user)
    return client


# -- what comes back ------------------------------------------------------------ #

@pytest.mark.django_db
def test_highlights_and_page_notes_come_back_as_one_list_newest_first(api, user):
    book = make_book(user, "Walden")
    highlight(user, book, 3, "I went to the woods", note="the opening", ago=30)
    page_note(user, book, 7, "Scan is blurry here", ago=20)
    highlight(user, book, 1, "Simplify, simplify", colour="green", ago=10)

    body = listing(api)

    assert body["count"] == 3
    assert [(e["kind"], e["text"]) for e in body["results"]] == [
        ("highlight", "Simplify, simplify"),
        ("note", "Scan is blurry here"),
        ("highlight", "I went to the woods"),
    ]
    first, second, third = body["results"]
    assert first["book"] == {"id": book.pk, "title": "Walden"}
    assert first["colour"] == "green"
    assert third["note"] == "the opening"
    # A page note has no colour and no separate note, and says so with empty
    # strings rather than by leaving the keys out.
    assert second["colour"] == "" and second["note"] == ""
    assert set(first) == set(second)


@pytest.mark.django_db
def test_paging_runs_across_both_kinds(api, user):
    """The union is paged by the database, so a page can straddle the kinds."""
    book = make_book(user, "Walden")
    for minutes in range(3):
        highlight(user, book, minutes, f"highlight {minutes}", ago=10 * minutes)
    for minutes in range(2):
        page_note(user, book, minutes, f"note {minutes}", ago=10 * minutes + 5)

    everything = [e["text"] for e in listing(api, limit=50)["results"]]
    assert everything == ["highlight 0", "note 0", "highlight 1", "note 1", "highlight 2"]

    middle = listing(api, limit=2, offset=2)
    assert middle["count"] == 5
    assert [e["text"] for e in middle["results"]] == everything[2:4]


# -- whose notes ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_another_readers_notes_never_appear(api, user, other_user, reader):
    """Both have annotated the same shared book; each sees only their own."""
    book = make_book(user, "Shared Walden", shared=True)
    highlight(user, book, 1, "the owner's passage")
    highlight(other_user, book, 1, "the reader's passage")
    page_note(other_user, book, 2, "the reader's note")

    assert [e["text"] for e in listing(api)["results"]] == ["the owner's passage"]
    assert sorted(e["text"] for e in listing(reader)["results"]) == [
        "the reader's note", "the reader's passage"]


@pytest.mark.django_db
def test_notes_on_a_book_no_longer_shared_drop_out(user, other_user, reader):
    """PRD §29: sharing can be revoked after the note was made. The per-book
    endpoint already 404s; the notebook must not be the way round it."""
    book = make_book(user, "Was Shared", shared=True)
    highlight(other_user, book, 1, "made while it was shared")
    assert listing(reader)["count"] == 1

    book.visibility = Book.Visibility.PRIVATE
    book.save()

    assert listing(reader)["count"] == 0


@pytest.mark.django_db
def test_notes_on_a_trashed_book_drop_out(api, user):
    book = make_book(user, "Binned")
    highlight(user, book, 1, "still on the row")
    book.trash()

    assert listing(api)["count"] == 0


@pytest.mark.django_db
def test_the_notebook_needs_a_signed_in_reader(db):
    assert Client().get(reverse("library:notebook")).status_code in (401, 403)


# -- filters -------------------------------------------------------------------- #

@pytest.fixture
def library(user):
    walden = make_book(user, "Walden")
    essays = make_book(user, "Essays")
    highlight(user, walden, 1, "Simplify, simplify", colour="yellow")
    highlight(user, walden, 2, "Morning air", note="read again in spring", colour="blue")
    highlight(user, essays, 4, "Self-reliance", colour="blue")
    page_note(user, essays, 5, "Pencil marks on this page")
    return walden, essays


@pytest.mark.django_db
def test_searching_matches_the_passage_the_note_and_the_title(api, library):
    def texts(q):
        return sorted(e["text"] for e in listing(api, q=q)["results"])

    assert texts("simplify") == ["Simplify, simplify"]
    assert texts("spring") == ["Morning air"], "a highlight's note is searchable"
    assert texts("pencil") == ["Pencil marks on this page"]
    assert texts("essays") == ["Pencil marks on this page", "Self-reliance"]


@pytest.mark.django_db
def test_a_colour_means_highlights_of_that_colour_only(api, library):
    texts = sorted(e["text"] for e in listing(api, colour="blue")["results"])
    assert texts == ["Morning air", "Self-reliance"], "page notes have no colour"


@pytest.mark.django_db
def test_kind_and_book_narrow_the_list(api, library):
    walden, essays = library
    assert [e["kind"] for e in listing(api, kind="note")["results"]] == ["note"]
    assert {e["kind"] for e in listing(api, kind="highlight")["results"]} == {"highlight"}
    assert {e["book"]["id"] for e in listing(api, book=essays.pk)["results"]} == {essays.pk}


@pytest.mark.django_db
def test_nonsense_filters_are_ignored_rather_than_refused(api, library):
    assert listing(api, colour="mauve", kind="poem", book="seven")["count"] == 4


# -- today's highlights --------------------------------------------------------- #

@pytest.mark.django_db
def test_todays_highlights_hold_still_all_day(api, user):
    book = make_book(user, "Walden")
    for n in range(10):
        highlight(user, book, n, f"passage {n}")

    url = reverse("library:notebook-daily")
    today = timezone.now().date().isoformat()
    first = api.get(url, {"today": today}).json()
    again = api.get(url, {"today": today}).json()

    assert first["date"] == today
    assert len(first["results"]) == notebook.DAILY_COUNT
    assert first == again, "reloading the page reshuffled the day's picks"


@pytest.mark.django_db
def test_another_day_brings_a_different_handful(user):
    book = make_book(user, "Walden")
    for n in range(12):
        highlight(user, book, n, f"passage {n}")

    start = date(2026, 3, 1)
    picks = {tuple(m.pk for m in notebook.daily(user, start + timedelta(days=n)))
             for n in range(5)}
    # Not a promise that two days never coincide — only that it is not a
    # fixed list wearing a date.
    assert len(picks) > 1


@pytest.mark.django_db
def test_todays_highlights_are_only_your_own_and_only_quotes(user, other_user):
    book = make_book(user, "Shared", shared=True)
    highlight(other_user, book, 1, "someone else's")
    highlight(user, book, 2, "")  # a rectangle with no text layer under it
    mine = highlight(user, book, 3, "mine")

    assert [m.pk for m in notebook.daily(user, date(2026, 3, 1))] == [mine.pk]


# -- export --------------------------------------------------------------------- #

def export(client, **params):
    return client.get(reverse("library:notebook-export"), params)


@pytest.mark.django_db
def test_one_book_exports_as_markdown_in_reading_order(api, user):
    book = make_book(user, "Walden: or, Life in the Woods")
    highlight(user, book, 9, "Simplify, simplify.", ago=60)
    highlight(user, book, 1, "I went to the woods\nbecause I wished to live deliberately",
              note="The *whole* book in a line.", ago=1)
    page_note(user, book, 9, "Compare with Emerson")
    Bookmark.objects.create(user=user, book=book, page=20, label="Conclusion")

    response = export(api, book=book.pk)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/markdown")
    assert response["Content-Disposition"] == (
        'attachment; filename="walden-or-life-in-the-woods-notes.md"')
    assert "no-store" in response["Cache-Control"]

    text = response.content.decode()
    assert text.startswith("# Walden: or, Life in the Woods\n")
    assert "2 highlights · 1 page note · 1 bookmark" in text
    # Page 2 before page 10, whatever order they were made in.
    assert text.index("## Page 2") < text.index("## Page 10")
    # A passage with a line break stays one blockquote.
    assert "> I went to the woods\n> because I wished to live deliberately" in text
    # Notes are the reader's own, and may already be Markdown.
    assert "The *whole* book in a line." in text
    assert "**Page note:** Compare with Emerson" in text
    assert "## Bookmarks\n\n- Page 21 — Conclusion" in text


@pytest.mark.django_db
def test_exporting_everything_covers_only_books_with_something_on_them(api, user):
    walden = make_book(user, "Walden")
    make_book(user, "Untouched")
    essays = make_book(user, "Essays")
    highlight(user, walden, 1, "Simplify")
    Bookmark.objects.create(user=user, book=essays, page=3)

    response = export(api)
    text = response.content.decode()

    assert response["Content-Disposition"] == 'attachment; filename="notebook-notes.md"'
    assert text.startswith("# Notebook\n")
    assert "## Walden" in text and "## Essays" in text
    assert "Untouched" not in text
    # Alphabetical, so the file reads like a shelf.
    assert text.index("## Essays") < text.index("## Walden")
    assert "### Page 2" in text, "pages nest a level under their book"


@pytest.mark.django_db
def test_an_export_is_only_ever_your_own_writing(user, other_user, reader):
    book = make_book(user, "Shared Walden", shared=True)
    highlight(user, book, 1, "the owner's passage")
    highlight(other_user, book, 2, "the reader's passage")

    text = export(reader, book=book.pk).content.decode()
    assert "the reader's passage" in text
    assert "the owner's passage" not in text


@pytest.mark.django_db
def test_a_book_you_cannot_open_cannot_be_exported(user, reader):
    """404, as everywhere else: a 403 would confirm the book exists."""
    private = make_book(user, "Diary")
    assert export(reader, book=private.pk).status_code == 404
    assert export(reader, book="not-a-number").status_code == 404


@pytest.mark.django_db
def test_a_title_with_a_line_break_does_not_break_its_heading(api, user):
    book = make_book(user, "Two\nLines")
    highlight(user, book, 0, "a passage")
    assert export(api, book=book.pk).content.decode().startswith("# Two Lines\n")


@pytest.mark.django_db
def test_an_empty_export_still_says_what_it_is(api, user):
    book = make_book(user, "Unread")
    day = timezone.now().date()
    text = export(api, book=book.pk, today=day.isoformat()).content.decode()
    assert text == f"# Unread\n\nExported from LumaIndex on {day.day} {day:%B %Y}\n"
