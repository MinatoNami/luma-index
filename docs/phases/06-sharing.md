# Phase 6 — Sharing

**Goal:** an owner marks a book shared; any authenticated user on the instance
can read it, with their own progress and annotations.

**Depends on:** Phases 2–5.

## Decisions

**The deletion matrix — the gap PRD §33 leaves open.** §33 says account deletion
"must define what happens to books previously shared by that user" and then does
not define it. Every case is written into `on_delete` arguments and tested with
two users; the table lives in `library/lifecycle.py`'s docstring.

| Event | Owner's data | Other readers' annotations |
| --- | --- | --- |
| Owner deletes their account | Books and files removed | Cascade. Annotations referencing a deleted book are a dangling reference and a privacy oddity — notes on something that no longer exists and cannot be seen. |
| Owner disabled by an admin | Retained | Shared books stay readable. Disabling is about *login*, not a content takedown. |
| Owner flips SHARED → PRIVATE | Retained | **Retained but inaccessible.** Re-sharing restores them; deleting on un-share means an accidental toggle destroys other people's work irrecoverably. |
| Owner deletes one book | Removed | Cascade with the book |
| Stored file goes missing | Source marked unavailable | Untouched |
| Owner empties their trash | Books and files gone | Cascade with the book |

The difference between this and whatever Django's defaults happened to be is the
whole point of writing it down.

**No ACLs.** §16 is explicit: `PRIVATE` and `SHARED`, nothing more. The richer
list (`INSTANCE_SHARED`, `USER_SHARED`, `GROUP_SHARED`) is §43 material. The
check sits behind one function so that model can be substituted later without
touching every view:

```python
def can_read(user, book) -> bool:
    return book.owner_id == user.id or book.visibility == Book.Visibility.SHARED
```

Every content, thumbnail, metadata and annotation path calls it.

**Owner-only fields stay owner-only.** The original filename and folder path
describe the owner's organisation, not the book, and a non-owner has no business
seeing them. They come from a separate serializer rather than a conditional
inside a shared one — conditionals are where the leak hides.

**Authorization is re-checked on every request.** A book that stops being shared
must stop being readable immediately, including for someone who fetched it a
moment ago. The storage layer is never an access-control boundary.

## What it added

Almost no new data: `Book.visibility` already existed from Phase 2. What changed
is that every Phase 3–5 queryset widened from "my books" to "books I can read" —
which is exactly why that base queryset needed to be one shared, tested
function. `ShareAudit` costs one small table and answers "who shared this, and
when?", which is the first question asked the first time something is visible
that should not be.

The decisive test: a second user with an empty library signs in, opens a shared
book, highlights a passage, and the owner sees neither the highlight nor any
change to their own progress.
