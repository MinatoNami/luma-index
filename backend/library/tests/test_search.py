"""Searching inside books.

The title filter answers "which book is this"; this answers "where did I read
that". The tests worth having are the ones about *where* a hit is, and about
whose books can be reached — a search across a shared instance is a queryset
away from being a way to read someone else's library.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from library.fulltext import index_book, search
from library.models import Book, BookPage

User = get_user_model()
PASSWORD = "a-long-enough-password-42"

WHALE = "Call me Ishmael. Some years ago, having little money in my purse."
STREETS = "There now is your insular city of the Manhattoes, belted by wharves."


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def stranger(db):
    return User.objects.create_user(email="stranger@example.com", password=PASSWORD)


def a_book(user, title, pages, *, shared=False):
    """A book with text already indexed, without going near a PDF."""
    book = Book.objects.create(
        owner=user, title=title, has_text_layer=True, page_count=len(pages),
        visibility=Book.Visibility.SHARED if shared else Book.Visibility.PRIVATE)
    BookPage.objects.bulk_create(
        [BookPage(book=book, page=i, text=t) for i, t in enumerate(pages)])
    from django.contrib.postgres.search import SearchVector
    BookPage.objects.filter(book=book).update(search=SearchVector("text", config="english"))
    return book


def results(client, term):
    return client.get(reverse("library:search"), {"q": term}).json()


@pytest.mark.django_db
def test_a_hit_says_which_page_it_is_on(owner):
    a_book(owner, "Moby-Dick", [WHALE, STREETS])

    body = results(signed_in(owner), "Manhattoes")

    assert body["count"] == 1
    assert body["results"][0]["page"] == 1, "a hit that cannot say where is half an answer"
    assert body["results"][0]["book"]["title"] == "Moby-Dick"


@pytest.mark.django_db
def test_a_hit_carries_the_sentence_it_was_found_in(owner):
    a_book(owner, "Moby-Dick", [WHALE])

    snippet = results(signed_in(owner), "Ishmael")["results"][0]["snippet"]

    assert "Ishmael" in snippet
    assert "<mark>" in snippet, "the point of a snippet is seeing the word in place"


@pytest.mark.django_db
def test_it_stems_rather_than_matching_letters(owner):
    a_book(owner, "Moby-Dick", ["The ship was sailing towards the harbour."])

    assert results(signed_in(owner), "sail")["count"] == 1


@pytest.mark.django_db
def test_a_phrase_in_quotes_is_a_phrase(owner):
    a_book(owner, "Moby-Dick", [WHALE, "Money in my hand, purse in my coat."])

    both = results(signed_in(owner), "money purse")["count"]
    phrase = results(signed_in(owner), '"money in my purse"')["count"]

    assert both == 2
    assert phrase == 1, "websearch syntax should treat a quoted phrase as one"


@pytest.mark.django_db
def test_search_never_reaches_another_user_s_private_book(owner, stranger):
    a_book(owner, "Private Notes", ["The password is hunter2 and the safe is behind."])

    assert results(signed_in(stranger), "hunter2")["count"] == 0


@pytest.mark.django_db
def test_a_shared_book_is_searchable_by_everyone_signed_in(owner, stranger):
    a_book(owner, "Shared Manual", ["The calibration constant is seventeen."], shared=True)

    body = results(signed_in(stranger), "calibration")

    assert body["count"] == 1
    assert body["results"][0]["book"]["title"] == "Shared Manual"


@pytest.mark.django_db
def test_a_trashed_book_drops_out_of_search(owner):
    book = a_book(owner, "Moby-Dick", [WHALE])
    assert results(signed_in(owner), "Ishmael")["count"] == 1

    book.trash()

    assert results(signed_in(owner), "Ishmael")["count"] == 0, (
        "the trash is where things go to stop being found")


@pytest.mark.django_db
def test_an_empty_query_returns_nothing_rather_than_everything(owner):
    a_book(owner, "Moby-Dick", [WHALE])

    for term in ("", "   "):
        assert results(signed_in(owner), term)["count"] == 0


@pytest.mark.django_db
def test_a_scan_is_not_indexed(owner):
    """`has_text_layer` is False, so there is nothing to extract and the rows
    would all be empty. index_book clears rather than adds."""
    book = Book.objects.create(owner=owner, title="A Scan", has_text_layer=False)
    BookPage.objects.create(book=book, page=0, text="left over from before")

    assert index_book(book, path=None) == 0
    assert BookPage.objects.filter(book=book).count() == 0


@pytest.mark.django_db
def test_reindexing_replaces_rather_than_accumulates(owner):
    """A replaced scan must not leave a page behind that says something the
    book no longer says."""
    book = a_book(owner, "Moby-Dick", [WHALE])
    assert BookPage.objects.filter(book=book).count() == 1

    a_book_pages = ["Entirely different words now."]
    BookPage.objects.filter(book=book).delete()
    BookPage.objects.bulk_create(
        [BookPage(book=book, page=0, text=a_book_pages[0])])

    assert BookPage.objects.filter(book=book).count() == 1


@pytest.mark.django_db
def test_deleting_a_book_takes_its_pages_with_it(owner):
    book = a_book(owner, "Moby-Dick", [WHALE, STREETS])
    assert BookPage.objects.filter(book=book).count() == 2

    book.delete()

    assert BookPage.objects.count() == 0


@pytest.mark.django_db
def test_the_search_function_never_widens_the_queryset_it_is_given(owner, stranger):
    """The permission boundary is the caller's queryset, so it is worth a test
    of its own that this function respects it."""
    a_book(owner, "Theirs", ["A distinctive incantation appears here."])

    assert search(Book.objects.filter(owner=stranger), "incantation") == []
    assert len(search(Book.objects.filter(owner=owner), "incantation")) == 1


@pytest.mark.django_db
def test_one_long_book_cannot_drown_out_the_others(owner):
    """A common word in a long book would otherwise return that book's whole
    concordance and nothing else."""
    a_book(owner, "The Long One", ["the harbour was quiet"] * 40)
    a_book(owner, "The Short One", ["the harbour was loud"])

    body = results(signed_in(owner), "harbour")
    titles = [r["book"]["title"] for r in body["results"]]

    assert titles.count("The Long One") <= 3
    assert "The Short One" in titles, "the short book must still be findable"
