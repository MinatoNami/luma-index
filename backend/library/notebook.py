"""Everything a reader has written, across every book.

Highlights and page notes were reachable only from inside the book they were
made in, so a passage you remembered marking meant remembering which book it
was in first. Kindle's notebook, Apple Books' Notes, Readwise and Zotero all
answer that with one place to look; PRD §43 lists it as "global highlight
search" and "annotation export".

Three things live here, all over the same rows and the same permission rule:

* `entries` — highlights and page notes as one list, newest first, filterable.
* `daily` — a few highlights to see again today, chosen without storing state.
* `to_markdown` — a book's annotations as a file another tool can take in.

The rule they share: a reader's own annotations, on books they can still open.
Sharing can be revoked after a note was made (PRD §29), and a note on a book
you can no longer read is not something this should hand back.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.db.models import CharField, Count, F, Max, Q, QuerySet, TextField, Value
from django.db.models.functions import MD5, Cast, Concat

from .models import Book, Bookmark, Highlight, PageNote
from .permissions import readable_books

KINDS = ("highlight", "note")

# Newest first is how you find what you marked last week; page order is how you
# reread what you marked in one book — the way Kindle's notebook lists it, and
# the way the export already reads.
ORDERS = {
    "recent": ("-created_at", "-id"),
    "page": ("book_title", "book_id", "page", "created_at", "id"),
}

# How many books the notebook's book list returns. Bounded like every list
# here; a household that has annotated more than this many books can search.
BOOK_LIMIT = 500

# A day's worth of looking back, not a review session: enough to be worth the
# glance on the way to a book, few enough that it is a glance.
DAILY_COUNT = 3


def _open_books(user) -> QuerySet[Book]:
    return readable_books(user).filter(deleted_at__isnull=True)


def entries(user, *, q: str = "", colour: str = "", kind: str = "",
            book_id: int | None = None, order: str = "recent") -> QuerySet:
    """Highlights and page notes as one queryset of dicts, newest first or in
    page order (see ORDERS).

    One UNION rather than two lists merged in Python, so `limit`/`offset` and
    `count` are the database's job and a deep page costs the same as the
    first. Both halves select the same columns in the same order — Django 5.2
    keeps `values()` in the order given, which is what makes the union line up.
    """
    books = _open_books(user)
    if book_id is not None:
        books = books.filter(pk=book_id)

    want_highlights = kind in ("", "highlight")
    # A colour is a property of a highlight. Asking for yellow and getting page
    # notes back as well would be a filter that does not filter.
    want_notes = kind in ("", "note") and not colour

    parts = []
    if want_highlights:
        highlights = Highlight.objects.filter(user=user, book__in=books)
        if colour:
            highlights = highlights.filter(colour=colour)
        if q:
            highlights = highlights.filter(
                Q(selected_text__icontains=q) | Q(note__icontains=q)
                | Q(book__title__icontains=q))
        parts.append(
            highlights.order_by().annotate(
                kind=Value("highlight", output_field=CharField()),
                book_title=F("book__title"),
                text=F("selected_text"),
            ).values("kind", "id", "book_id", "book_title", "page", "text", "note",
                     "colour", "created_at", "updated_at"))

    if want_notes:
        notes = PageNote.objects.filter(user=user, book__in=books)
        if q:
            notes = notes.filter(Q(body__icontains=q) | Q(book__title__icontains=q))
        parts.append(
            notes.order_by().annotate(
                kind=Value("note", output_field=CharField()),
                book_title=F("book__title"),
                text=F("body"),
                # Page notes have neither; empty rather than NULL so a client
                # never has to tell the two kinds apart by a missing key.
                note_=Value("", output_field=TextField()),
                colour_=Value("", output_field=CharField()),
            ).values("kind", "id", "book_id", "book_title", "page", "text", "note_",
                     "colour_", "created_at", "updated_at"))

    ordering = ORDERS.get(order, ORDERS["recent"])
    if not parts:
        return Highlight.objects.none().values()
    if len(parts) == 1:
        return parts[0].order_by(*ordering)
    return parts[0].union(parts[1], all=True).order_by(*ordering)


def books(user) -> tuple[list[dict], dict[str, int], int]:
    """The books a reader has written on, with how much, most recent first.

    What the notebook's book list shows. Without it, narrowing to one book
    meant finding an entry from that book first and following its title — the
    filter existed but could not be discovered. Two aggregates and a merge
    rather than a UNION, because the answer is one row per book, and a
    household library is a few hundred books at the very most.

    Returns (books, totals, count): `totals` is highlights and notes across
    every book, so the kind filter can say how many of each there are.
    """
    open_books = _open_books(user)
    rows: dict[int, dict] = {}

    for model, key in ((Highlight, "highlights"), (PageNote, "notes")):
        counts = (model.objects.filter(user=user, book__in=open_books)
                  .values("book_id").annotate(n=Count("id"), last=Max("created_at"))
                  .order_by())
        for row in counts:
            entry = rows.setdefault(row["book_id"], {
                "id": row["book_id"], "highlights": 0, "notes": 0, "last_at": row["last"]})
            entry[key] = row["n"]
            entry["last_at"] = max(entry["last_at"], row["last"])

    titles = dict(Book.objects.filter(pk__in=rows).values_list("pk", "title"))
    ordered = sorted(rows.values(), key=lambda r: (r["last_at"], r["id"]), reverse=True)
    for row in ordered:
        row["title"] = titles.get(row["id"], "")

    totals = {"highlights": sum(r["highlights"] for r in ordered),
              "notes": sum(r["notes"] for r in ordered)}
    return ordered[:BOOK_LIMIT], totals, len(ordered)


def serialise(row: dict) -> dict:
    """One union row in the shape the API promises."""
    return {
        "kind": row["kind"],
        "id": row["id"],
        "book": {"id": row["book_id"], "title": row["book_title"]},
        "page": row["page"],
        "text": row["text"],
        # The second half of the union names these note_ and colour_, but a
        # UNION takes its column names from the first half, so whichever kind
        # comes back the keys are the highlight's.
        "note": row.get("note", row.get("note_", "")) or "",
        "colour": row.get("colour", row.get("colour_", "")) or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def daily(user, today: date, *, count: int = DAILY_COUNT) -> list[Highlight]:
    """A few highlights to see again today.

    Readwise's daily review, without the review: no schedule to store, no state
    to drift. The order is a hash of each highlight's id with the user and the
    date, so the choice holds still all day — reloading the home page does not
    reshuffle it — and is a different handful tomorrow. Only highlights that
    carry text: a quote is the point, and a bare rectangle on a page is not one.
    """
    seed = f":{user.pk}:{today.isoformat()}"
    return list(
        Highlight.objects
        .filter(user=user, book__in=_open_books(user))
        .exclude(selected_text="")
        .select_related("book")
        .annotate(shuffle=MD5(Concat(Cast("id", CharField()), Value(seed))))
        .order_by("shuffle")[:count]
    )


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

@dataclass
class _Page:
    highlights: list[Highlight]
    notes: list[PageNote]


def _quote(text: str) -> str:
    """A passage as a blockquote that stays one, whatever line breaks it had."""
    lines = [line.rstrip() for line in text.strip().splitlines()] or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _heading(text: str) -> str:
    # A title with a newline in it would end the heading and start a paragraph.
    return " ".join(text.split())


def _book_section(book: Book, pages: dict[int, _Page], bookmarks: list[Bookmark],
                  level: int) -> list[str]:
    h = "#" * level
    out: list[str] = []
    for number in sorted(pages):
        page = pages[number]
        out.append(f"{h}# Page {number + 1}")
        out.append("")
        for mark in page.highlights:
            if mark.selected_text.strip():
                out.append(_quote(mark.selected_text))
                out.append("")
            if mark.note.strip():
                out.append(mark.note.strip())
                out.append("")
        for note in page.notes:
            out.append(f"**Page note:** {note.body.strip()}")
            out.append("")

    if bookmarks:
        out.append(f"{h}# Bookmarks")
        out.append("")
        for mark in bookmarks:
            label = f" — {_heading(mark.label)}" if mark.label.strip() else ""
            out.append(f"- Page {mark.page + 1}{label}")
        out.append("")
    return out


def to_markdown(user, books: list[Book], *, exported_on: date) -> str:
    """The reader's annotations on `books`, as Markdown.

    Page by page in reading order rather than in the order they were made: a
    file you open in Obsidian a year later reads like the book did. Plain
    CommonMark — blockquotes, headings, a list — so it survives being pasted
    anywhere, and notes are passed through as written, since they are the
    reader's own and may already be Markdown.
    """
    book_ids = [b.pk for b in books]
    highlights = Highlight.objects.filter(user=user, book_id__in=book_ids).order_by(
        "page", "created_at")
    notes = PageNote.objects.filter(user=user, book_id__in=book_ids).order_by(
        "page", "created_at")
    bookmarks = Bookmark.objects.filter(user=user, book_id__in=book_ids).order_by("page")

    pages: dict[int, dict[int, _Page]] = defaultdict(dict)
    for mark in highlights:
        pages[mark.book_id].setdefault(mark.page, _Page([], [])).highlights.append(mark)
    for note in notes:
        pages[note.book_id].setdefault(note.page, _Page([], [])).notes.append(note)
    marks: dict[int, list[Bookmark]] = defaultdict(list)
    for mark in bookmarks:
        marks[mark.book_id].append(mark)

    stamp = f"{exported_on.day} {exported_on.strftime('%B %Y')}"
    single = len(books) == 1
    out: list[str] = []

    if single:
        book = books[0]
        on_book = pages[book.pk].values()
        counts = _counts(sum(len(p.highlights) for p in on_book),
                         sum(len(p.notes) for p in on_book),
                         len(marks[book.pk]))
        out += [f"# {_heading(book.title)}", "", f"Exported from LumaIndex on {stamp}{counts}",
                ""]
        out += _book_section(book, pages[book.pk], marks[book.pk], level=1)
    else:
        out += ["# Notebook", "", f"Exported from LumaIndex on {stamp}", ""]
        for book in books:
            if not pages[book.pk] and not marks[book.pk]:
                continue
            out += [f"## {_heading(book.title)}", ""]
            out += _book_section(book, pages[book.pk], marks[book.pk], level=2)

    return "\n".join(out).rstrip() + "\n"


def _counts(highlights: int, notes: int, bookmarks: int) -> str:
    parts = []
    for n, one, many in ((highlights, "highlight", "highlights"),
                         (notes, "page note", "page notes"),
                         (bookmarks, "bookmark", "bookmarks")):
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    return f" · {' · '.join(parts)}" if parts else ""


def books_with_annotations(user) -> list[Book]:
    """Every open book the reader has written anything on, by title."""
    books = _open_books(user)
    return list(
        books.filter(
            Q(highlights__user=user) | Q(page_notes__user=user) | Q(bookmarks__user=user)
        ).distinct().order_by("title", "pk")
    )
