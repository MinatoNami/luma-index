# Phase 3 — Library

**Goal:** browse, search, sort, filter, and organise books into nested
collections that are completely independent of the Drive folder structure they
were imported from.

**Depends on:** Phase 2 (`Book`, `BookSource`).

---

## Decide before writing code

### D1. Is "Favourite" a collection or a flag?
PRD §12 lists Favourites among the "standard virtual/system views". Two shapes:

- **A boolean on a per-user record.** Simple, fast to filter, one query.
- **A system-created `Collection`.** Uniform code path, but every user then owns
  a magic row whose name they can rename or delete.

Recommendation: **a flag**, on a `UserBookState` row (see below). System views
should not be user-editable rows; a user who renames "Favourites" to "Later"
and then finds the star icon filling a differently-named list is a bug report.

### D2. Where does per-user, per-book state live?
Favourites, `last_opened_at`, and "added to my library" apply to books a user
may not own (Phase 6 lets them read shared books). Reading progress is already
per-user, but progress is not the same thing as a favourite.

Recommendation: one `UserBookState` model, unique on `(user, book)`, holding
the small per-user flags. Reading progress stays separate — it is written
constantly and read differently.

### D3. Search implementation
`icontains` over title and filename is honest for a few thousand books and
needs no extra machinery. PostgreSQL trigram (`pg_trgm`) adds fuzzy matching
and an index for one migration's cost.

Recommendation: start with `icontains`, add a `pg_trgm` GIN index when the
library gets big enough to notice. Full-text search over PDF *contents* is
explicitly out of MVP scope (§42) — do not let this decision drift into it.

### D4. Collection nesting rules
Arbitrary depth invites cycles and unbounded recursive queries.

Recommendation: cap depth (4 is generous), reject a parent that is a
descendant of the collection being moved, and validate both server-side. A
cycle here means an infinite loop in the sidebar renderer.

---

## Data model

```text
Collection
  user          FK -> User, on_delete=CASCADE
  name
  parent        FK -> self, null=True, on_delete=CASCADE
  position      manual ordering within a parent
  created_at, updated_at
  unique_together: (user, parent, name)

CollectionBook                       many-to-many with ordering
  collection    FK, on_delete=CASCADE
  book          FK, on_delete=CASCADE
  position
  added_at
  unique_together: (collection, book)

UserBookState                        per-user flags on any readable book
  user          FK, on_delete=CASCADE
  book          FK, on_delete=CASCADE
  is_favourite  bool
  added_at      when this user added a shared book to their library
  last_opened_at
  unique_together: (user, book)
```

A book in three collections is three `CollectionBook` rows and one PDF — PRD
§11's requirement that logical organisation never touches Drive falls out of
the model rather than needing to be enforced.

---

## Virtual views

PRD §12 lists six. None of them is a stored collection:

| View | Query |
| --- | --- |
| Continue Reading | `ReadingProgress` where `0 < percentage < 100`, by `last_opened_at` |
| Recently Added | `Book.created_at` (owned) / `UserBookState.added_at` (shared) |
| Recently Opened | `UserBookState.last_opened_at` |
| Favourites | `UserBookState.is_favourite` |
| Shared With Me | `visibility=SHARED` and `owner != request.user` (Phase 6) |
| Unsorted / Inbox | owned books with no `CollectionBook` row |

Expose them as a filter parameter, not as fake collection IDs — otherwise every
collection endpoint grows special cases for six magic values.

---

## API

```text
GET    /api/library/books/          ?search= &view= &collection= &sort= &page=
GET    /api/library/books/{id}/
PATCH  /api/library/books/{id}/     title, visibility (owner only)
GET    /api/library/books/{id}/thumbnail

POST   /api/library/books/{id}/favourite      idempotent
DELETE /api/library/books/{id}/favourite

GET    /api/collections/            nested tree
POST   /api/collections/
PATCH  /api/collections/{id}/       rename, reparent, reorder
DELETE /api/collections/{id}/       ?cascade=false detaches children
POST   /api/collections/{id}/books/ {book_id}
DELETE /api/collections/{id}/books/{book_id}/
```

Sort keys: `title`, `added`, `opened`, `progress`, `size`, `pages`.

**Every queryset filters by the requesting user before anything else.** The
list endpoint is the one most likely to leak another user's private books, and
a `get_queryset` that starts from `Book.objects.all()` is how it happens.

Paginate from the first commit. An unpaginated library endpoint works fine for
the developer with 12 books and falls over on a real import.

---

## Backend work

1. `library` app: models, migrations, serializers, viewsets.
2. A single permission-scoped base queryset that every library view builds on:
   owned books, plus shared books once Phase 6 lands.
3. Filter/sort/search backends and pagination.
4. Collection tree serialization with a depth cap and cycle rejection.
5. Thumbnail delivery through the authorization boundary — a thumbnail of a
   private book is still private.
6. `N+1` prevention: `select_related("owner")`,
   `prefetch_related("sources")`, and progress annotated in one query rather
   than fetched per card.

## Frontend work

- Grid and list views, toggle persisted in `UserSettings`.
- Cover, title, filename, progress bar, original Drive path (PRD §15).
- Collection sidebar: nested, drag to add, rename inline.
- Search field, sort menu, filter chips.
- Responsive down to phone width; tablet is a primary target (§39).
- Skeleton states — thumbnails arrive after import, not during.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Library list leaks another user's private books | One shared, tested base queryset; a permission test per view. |
| Card grid triggers N+1 queries | Annotate progress; assert query counts in tests. |
| Deleting a collection deletes books | `CollectionBook` cascade removes the *membership* only. Worth an explicit test — it is an easy thing to get backwards. |
| Deep nesting hangs the sidebar | Depth cap plus cycle rejection, server-side. |

## Acceptance (PRD §45)

Criteria **10** (independent nested collections) and **11** (reorganising never
changes Drive).

Add: a book in three collections has one `BookSource`; deleting a collection
leaves the books; a second user's library request never returns the first
user's private books.

**Rough size:** medium. Mostly CRUD; the care goes into the base queryset and
pagination.
