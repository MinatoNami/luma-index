"""Which covers stand in for a folder.

A folder has no picture of its own, so it borrows the covers of the books
inside it: the first few, in the order the folder itself lists them.  Only the
book ids travel — the browser then fetches the same per-book thumbnails it
already shows in the grid.

That is the whole design decision.  Compositing a folder image on the server
would mean storing it, and storing it would mean invalidating it on every add,
move, trash, restore, delete and re-render, up the ancestor chain if previews
recursed.  Worse, a stored composite is stale by construction: drop a book into
a folder and the picture stays wrong until a worker catches up.  Borrowed
covers are simply correct on the next render.

One level of lookahead, no deeper.  A folder holding nothing but subfolders —
the shape every ZIP import produces at its root — would otherwise show nothing
at all, which is exactly the folder a reader most wants to recognise.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from django.db.models import F, Window
from django.db.models.functions import RowNumber

from .models import Book, Folder

# Four fills a 2x2 mosaic. More tiles would each be too small to recognise at
# grid size, and each one is a separate request the browser has to make.
PREVIEW_LIMIT = 4


def collect_preview_book_ids(
    folders: Iterable[Folder], *, limit: int = PREVIEW_LIMIT
) -> dict[int, list[int]]:
    """Cover-bearing book ids for each folder, in three queries regardless of
    how many folders are asked about.

    Every folder passed in gets an entry, empty list included — callers use
    presence in the mapping to tell "no covers" from "not looked up yet".
    """
    folders = [f for f in folders if f.pk]
    if not folders:
        return {}

    ids = [f.pk for f in folders]
    previews = _top_books_per_folder(ids, limit)
    result = {fid: previews.get(fid, []) for fid in ids}

    short = [fid for fid in ids if len(result[fid]) < limit]
    if short:
        _top_up_from_children(result, short, limit)
    return result


def _top_up_from_children(
    result: dict[int, list[int]], parent_ids: list[int], limit: int
) -> None:
    """Borrow from immediate subfolders, one cover from each in turn.

    Round-robin rather than draining the first subfolder, because draining it
    makes the parent a pixel-perfect copy of its own first child — two tiles in
    the same grid showing the same picture, which is worse than no picture at
    all.  Taking one from each child instead makes the parent look like a
    summary of what is under it.
    """
    children = list(
        Folder.objects.filter(parent_id__in=parent_ids, deleted_at__isnull=True)
        .order_by("name", "id")
        .values_list("parent_id", "id")
    )
    if not children:
        return

    books = _top_books_per_folder([child_id for _, child_id in children], limit)

    by_parent: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in children:
        by_parent[parent_id].append(child_id)

    for parent_id, child_ids in by_parent.items():
        borrowed = result[parent_id]
        for position in range(limit):
            if len(borrowed) >= limit:
                break
            for child_id in child_ids:
                covers = books.get(child_id, ())
                if position >= len(covers):
                    continue
                book_id = covers[position]
                # A book lives in exactly one folder, but the direct pass may
                # already have supplied this one.
                if book_id in borrowed:
                    continue
                borrowed.append(book_id)
                if len(borrowed) >= limit:
                    break


def _top_books_per_folder(folder_ids: list[int], limit: int) -> dict[int, list[int]]:
    """At most `limit` books per folder, ranked in the database.

    Windowed rather than fetched-and-sliced: a folder holding two thousand books
    would otherwise drag two thousand rows across the wire to show four covers.
    """
    if not folder_ids:
        return {}

    rows = (
        Book.objects.filter(folder_id__in=folder_ids, deleted_at__isnull=True)
        .exclude(thumbnail_path="")
        .annotate(
            rank=Window(
                expression=RowNumber(),
                partition_by=[F("folder_id")],
                # Ties broken by id so the mosaic is the same picture on every
                # visit; a folder that reshuffles is not a thing you recognise.
                order_by=[F("title").asc(), F("id").asc()],
            )
        )
        .filter(rank__lte=limit)
        .values_list("folder_id", "id", "rank")
    )

    grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for folder_id, book_id, rank in rows:
        grouped[folder_id].append((rank, book_id))
    return {
        folder_id: [book_id for _, book_id in sorted(pairs)]
        for folder_id, pairs in grouped.items()
    }
