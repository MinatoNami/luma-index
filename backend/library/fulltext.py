"""Searching inside books.

PRD §42 rules out OCR and semantic/vector search. It does not rule this out:
keyword search over a text layer the document already has, which is what every
comparable library server offers and the one thing the title filter cannot do.
A scan stays unsearchable, and `Book.has_text_layer` is what says so.

PostgreSQL does the work — `to_tsvector` on the row, a GIN index over it, and
`ts_rank` to order. No new service, no new dependency, which is the same reason
the ingest worker is a polling loop rather than a broker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db import transaction

from .documents import extract_pages
from .models import Book, BookPage

logger = logging.getLogger("lumaindex.fulltext")

# The dictionary decides stemming and stop words. English is a guess, and the
# wrong one for a French library — but a wrong stemmer still matches whole
# words, whereas no configuration at all matches nothing useful.
CONFIG = "english"

# Rows per INSERT. A nine-hundred-page book in one statement is a large
# transaction to hold open while the worker has other jobs waiting.
BATCH = 200

# Enough to find the passage, not enough to reprint the book in a result list.
MAX_HITS = 50

# At most this many pages from any one book. Without it, searching a common
# word in a four-hundred-page reference work returns four hundred hits from
# that one book and nothing else — the result list becomes a concordance for
# whichever book is longest, rather than an answer to "which of my books talks
# about this".
PER_BOOK = 3


@dataclass(frozen=True)
class Hit:
    book: Book
    page: int
    snippet: str
    rank: float


def index_book(book: Book, path: Path) -> int:
    """(Re)index one book's pages. Returns how many pages carried text.

    Replaces rather than merges: a book whose file was swapped for a re-scan
    would otherwise keep the old pages alongside the new ones, and a search
    would find a page that no longer says that.
    """
    if not book.has_text_layer:
        # Nothing to index, and nothing to keep from an earlier attempt.
        deleted, _ = BookPage.objects.filter(book=book).delete()
        return 0

    rows = [BookPage(book=book, page=index, text=text)
            for index, text in extract_pages(path)]

    with transaction.atomic():
        BookPage.objects.filter(book=book).delete()
        BookPage.objects.bulk_create(rows, batch_size=BATCH)
        # One UPDATE rather than a vector per row on the way in: the column
        # exists so the index has something to index, and computing it in the
        # database avoids shipping every page back and forth.
        BookPage.objects.filter(book=book).update(
            search=SearchVector("text", config=CONFIG))

    logger.info("indexed book text",
                extra={"event": "fulltext.indexed", "book_id": book.pk,
                       "pages": len(rows)})
    return len(rows)


def search(books, term: str, *, limit: int = MAX_HITS) -> list[Hit]:
    """Pages matching `term`, best first, within `books`.

    `books` is the caller's already-permission-scoped queryset. This function
    narrows it and never widens it: passing the wrong queryset here is how a
    search endpoint becomes a way to read someone else's library.
    """
    term = term.strip()
    if not term:
        return []

    query = SearchQuery(term, config=CONFIG, search_type="websearch")
    rows = (
        BookPage.objects
        .filter(book__in=books, search=query)
        .annotate(
            rank=SearchRank("search", query),
            snippet=SearchHeadline(
                "text", query, config=CONFIG,
                start_sel="<mark>", stop_sel="</mark>",
                max_words=30, min_words=15, highlight_all=False),
        )
        .select_related("book", "book__folder")
        # Over-fetch, because the per-book cap below throws rows away and the
        # caller asked for `limit` results, not `limit` candidates.
        .order_by("-rank", "book_id", "page")[:limit * PER_BOOK * 2]
    )

    hits: list[Hit] = []
    per_book: dict[int, int] = {}
    for row in rows:
        seen = per_book.get(row.book_id, 0)
        if seen >= PER_BOOK:
            continue
        per_book[row.book_id] = seen + 1
        hits.append(Hit(book=row.book, page=row.page, snippet=row.snippet, rank=row.rank))
        if len(hits) >= limit:
            break
    return hits
