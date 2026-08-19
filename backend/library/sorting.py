"""One sort order across folders, books, and the trash.

Folders and books are different tables with different column names — a folder
has a `name`, a book has a `title`, and only one of them has a size — so left
alone each listing would grow its own vocabulary and the interface would have
to remember which words worked where. `?sort=name` means the same thing
everywhere, and a field a table does not have falls back rather than 500s.

Ordering by type is not here on purpose. The response keeps folders and books
in separate lists, so "folders first" or "files first" is a choice about which
block to draw first — a question for the page, not the database.
"""

from __future__ import annotations

FOLDER_FIELDS = {
    "name": "name",
    "added": "created_at",
    "modified": "updated_at",
    "trashed": "deleted_at",
}

BOOK_FIELDS = {
    "name": "title",
    # Kept because the published schema has always named it this.
    "title": "title",
    "added": "created_at",
    "modified": "updated_at",
    "size": "source__file_size",
    "trashed": "deleted_at",
}

DEFAULT = "name"


def order_by(sort: str | None, fields: dict[str, str]) -> list[str]:
    """Turn `?sort=-added` into the arguments for `.order_by()`.

    Always ends with the tie-break the caller did not ask for: two books added
    in the same second would otherwise come back in whatever order the database
    felt like, and a listing that reshuffles between refreshes looks broken.
    """
    raw = (sort or "").strip()
    descending = raw.startswith("-")
    key = raw.lstrip("-") or DEFAULT

    column = fields.get(key)
    if column is None:
        # Asking folders for "largest first" is asking for something they do not
        # have, so the direction goes with the field: plain A-Z, not Z-A, which
        # would be an order nobody chose.
        return [fields[DEFAULT], "pk"]

    return [f"-{column}" if descending else column, "pk"]


def apply(queryset, sort: str | None, fields: dict[str, str]):
    return queryset.order_by(*order_by(sort, fields))
