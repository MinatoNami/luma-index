# Phase 6 — Sharing

**Goal:** an owner marks a book shared; any authenticated user on the instance
can read it, with their own progress and annotations, and **without any access
to the owner's Google Drive**.

**Depends on:** Phases 2–5.

---

## Decide before writing code

### D1. The deletion matrix — **the gap PRD §33 explicitly leaves open**
§33 says account deletion "must define what happens to books previously shared
by that user" and then does not define it. Every case below needs an answer
written into `on_delete` and tested with two users:

| Event | Owner's data | **Other readers' progress, bookmarks, highlights** |
| --- | --- | --- |
| Owner deletes their account | Books removed | **Decide.** Cascade, or retain orphaned? |
| Owner disables their account (admin) | Retained | Decide: still readable, or hidden? |
| Owner flips SHARED → PRIVATE | Retained | Retained but inaccessible — must not be deleted |
| Owner deletes one book | Removed | Cascade with the book |
| Drive file goes missing | Source marked unavailable | Untouched (§13) |
| Owner disconnects Drive | Books retained, sources orphaned | Untouched (§33) |

Recommendation, matching §33's own suggestion:

- **Account deletion** → the owner's books go, and other users' annotations on
  them cascade. Retaining annotations that reference a deleted book is a
  dangling reference and a privacy oddity — the reader kept notes on something
  that no longer exists and that they cannot see.
- **Account disabled** → shared books stay readable. Disabling is an
  administrative action about *login*, not a content takedown.
- **SHARED → PRIVATE** → other readers lose access; their annotations are
  **retained**, so re-sharing restores them. Deleting on un-share means an
  accidental toggle destroys other people's work irrecoverably.

Write this table into the models as explicit `on_delete=` arguments and test
the two-user cases. It is the difference between a considered policy and
whatever Django's defaults happened to be.

### D2. How a shared reader gets bytes
The reader has no Drive access — that is the whole point (§18).

Recommendation: Django fetches and caches using the **owner's**
`DriveConnection`, then serves from cache to any authorized reader. Consequences
to handle deliberately:

- If the owner's token has expired, a shared read fails for a file not yet
  cached. Return a clear "temporarily unavailable" state, never the owner's
  error detail, and never anything about the owner's credentials.
- A cached file outliving the share is a leak. **Authorization is checked on
  every request, including cache hits** — the cache is a performance detail, not
  an access-control boundary.
- The owner's `provider_file_id`, `original_path`, and Drive account must not
  appear in any response to a non-owner. §15 asks for the Drive path in the
  library view; that field is for the owner only.

### D3. Do not build ACLs
§16 is explicit: `PRIVATE` and `SHARED`, nothing more. The future list
(`INSTANCE_SHARED`, `USER_SHARED`, `GROUP_SHARED`) is §43 material.

Keep the permission check behind one function so the richer model can be
substituted later without touching every view:

```python
def can_read(user, book) -> bool:
    return book.owner_id == user.id or book.visibility == Book.Visibility.SHARED
```

Every content, thumbnail, metadata, and annotation path calls this one function.

---

## Data model

Almost nothing new — `Book.visibility` already exists from Phase 2. What
changes is that every queryset now considers shared books.

```text
Book.visibility   PRIVATE | SHARED     (default PRIVATE, PRD §16)

ShareAudit                             optional but recommended
  book, actor, from_visibility, to_visibility, created_at
```

`ShareAudit` costs one small table and answers "who shared this, and when?" —
the first question asked the first time something is visible that should not
have been.

---

## API

```text
GET   /api/shared/books/              books shared by others
PATCH /api/books/{id}/                {visibility} — owner only
```

No new reading endpoints. Every Phase 3–5 endpoint widens from "my books" to
"books I can read", which is exactly why that base queryset from Phase 3 needs
to be one shared, tested function.

---

## Backend work

1. A DRF permission class wrapping `can_read`, applied to every book-scoped
   view, plus `IsOwner` for mutations.
2. Widen the library base queryset to owned + shared.
3. Owner-only serializer fields (Drive path, file ID, source detail) via a
   separate serializer, not a conditional inside one — conditionals are where
   the leak hides.
4. Content delivery using the owner's connection (D2), with authorization
   re-checked on cache hits.
5. Implement the D1 matrix as `on_delete` arguments plus an account-deletion
   routine.
6. Account lifecycle endpoints from §33: disconnect Drive, remove library,
   delete reading data, delete account.

## Frontend work

- A share toggle on owned books, with a plain statement of what it means:
  every signed-in user on this instance can read it, and no, this does not
  change anything in Google Drive (§16).
- A "Shared With Me" view.
- Owner attribution on shared books.
- Shared books addable to the reader's own collections (§17).

---

## Risks

| Risk | Mitigation |
| --- | --- |
| A private book leaks through a path that forgot to check | One `can_read`, called everywhere; a permission test matrix in Phase 7. |
| Cached PDF served after un-sharing | Authorization on every request, cache hits included. Test un-share then re-request. |
| Owner's Drive identity leaks to readers | Separate owner/reader serializers; assert absence in tests. |
| Un-sharing destroys other people's annotations | D1: retain on un-share. |
| Non-Google user cannot read a shared book | §17's whole point — test with a user who has no `DriveConnection` at all. |

## Acceptance (PRD §45)

Criteria **17–24**: private by default; owners can share; non-Google users can
read; readers never touch the owner's credentials; Django authorizes every
content request; per-reader state is independent; no access to another user's
private books or annotations.

The decisive test: a user with **no Google account** signs in, opens a shared
book, highlights a passage, and the owner sees neither the highlight nor any
change to their own progress.

**Rough size:** medium, but the highest-risk phase — it is where a permission
mistake becomes a privacy incident rather than a bug.
