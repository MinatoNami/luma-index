# Phase 3 — Library

**Goal:** browse, search, sort, filter, and organise books into nested
collections independent of the folder tree.

**Depends on:** Phase 2 (`Book`, `BookSource`).

## Decisions

**Favourite is a flag, not a collection.** PRD §12 lists Favourites among the
virtual views. A system-created `Collection` would give a uniform code path but
leave every user owning a magic row they can rename or delete — a user who
renames "Favourites" to "Later" and then finds the star icon filling a
differently-named list is a bug report. It is a boolean on `UserBookState`.

**Per-user, per-book state lives in one model.** Favourites, `last_opened_at`
and "added to my library" apply to books a user may not own, since Phase 6 lets
them read shared ones. One `UserBookState`, unique on `(user, book)`, holds the
small flags. Reading progress stays separate: it is written constantly and read
differently.

**Search is `icontains` over title.** Honest for a few thousand books and needs
no extra machinery. A `pg_trgm` GIN index adds fuzzy matching for one
migration's cost when the library gets big enough to notice; it has not.
Full-text search over PDF *contents* is out of MVP scope (§42) — this decision
must not drift into it.

**Collection nesting is capped and cycle-checked** at the same depth as folders,
validated server-side, rejecting a parent that is a descendant of the collection
being moved. A cycle here is an infinite loop in the sidebar renderer.

## Virtual views

PRD §12 lists six. None is a stored collection:

| View | Query |
| --- | --- |
| Continue Reading | `ReadingProgress` where `0 < percentage < 100`, by `last_opened_at` |
| Recently Added | `Book.created_at` (owned) / `UserBookState.added_at` (shared) |
| Recently Opened | `UserBookState.last_opened_at` |
| Favourites | `UserBookState.is_favourite` |
| Shared With Me | `visibility=SHARED` and `owner != request.user` |
| Unsorted | owned books with no `CollectionBook` row |

They are a filter parameter, not fake collection ids — otherwise every
collection endpoint grows special cases for six magic values.

## Rules that carried

- **Every queryset filters by the requesting user before anything else.** The
  list endpoint is the one most likely to leak another user's private books, and
  a `get_queryset` starting from `Book.objects.all()` is how it happens.
- **Paginate from the first commit.** An unpaginated library endpoint is fine
  with twelve books and falls over on a real import.
- **Deleting a collection deletes memberships, not books.** `CollectionBook`
  cascades; the books do not. Worth an explicit test — it is easy to get
  backwards.
- **Annotate progress rather than fetching it per card,** with
  `select_related("owner")` and `prefetch_related("sources")`, and assert query
  counts in tests.
- A book in three collections is three `CollectionBook` rows and one PDF, so
  §11's requirement that logical organisation never touch the source hierarchy
  falls out of the model rather than needing enforcement.
