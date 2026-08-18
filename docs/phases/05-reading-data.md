# Phase 5 — Bookmarks, highlights, notes

**Goal:** private, per-user annotations that survive zoom changes, window
resizes, and moving between a phone and a desktop — without ever modifying the
original PDF.

**Depends on:** Phase 4 (the reader and its text layer).

---

## Decide before writing code

### D1. Highlight anchoring format — **decide before the first highlight is stored**
PRD §23 says "store positions independently from viewport pixels" and stops
there. This is the one schema in the project that is genuinely painful to
change later: once users have highlights, a format change means migrating
coordinates you can no longer recompute, because the mapping depended on the
viewport that produced them.

Recommendation — store, per highlight:

```jsonc
{
  "v": 1,                       // schema version, from the very first write
  "page": 42,                   // 0-indexed
  "quads": [                    // PDF user space, origin bottom-left
    { "x1": 72.0, "y1": 640.2, "x2": 288.4, "y2": 652.8 }
  ],
  "text_offsets": {             // fallback anchor if quads ever fail
    "start": 1840, "end": 1902
  }
}
```

Why this shape:

- **PDF user space, not screen pixels.** Convert with PDF.js's
  `viewport.convertToPdfPoint()`. A point in user space means the same thing at
  any zoom, on any screen, forever.
- **Quads, not a bounding box.** A selection spanning three lines is three
  rectangles; a single box would highlight the margin between them.
- **A version field from day one.** Adding one later requires guessing what
  unversioned rows meant.
- **Character offsets as a secondary anchor.** If a source file is replaced by a
  re-scan with slightly different geometry, offsets can often re-locate the
  selection when coordinates cannot.

### D2. What happens when the text layer is missing
Scanned PDFs (PRD §27) have no selectable text, so text-anchored highlights are
impossible.

Recommendation: allow **bookmarks and page-level notes** on scanned books, and
disable text highlighting with an explanation. OCR is deferred (§27, §42) —
this is the honest interim, and it keeps the door open: an OCR pass later adds
a text layer without invalidating anything stored now.

### D3. Deleting a book that has annotations
PRD §35 says failures must not destroy reader metadata, and §13 says an
unavailable Drive file must not delete annotations.

Recommendation: annotations hang off `Book`, never off `BookSource`. A missing
Drive file marks the *source* unavailable; the book, and everything a user
wrote on it, stays. Get the FK targets right and this is automatic.

---

## Data model

```text
Bookmark
  user           FK, on_delete=CASCADE
  book           FK, on_delete=CASCADE     <- Book, never BookSource (D3)
  page           int
  page_fraction  float, null=True          same convention as progress
  label          char, blank
  created_at
  index: (user, book, page)

Highlight
  user           FK, on_delete=CASCADE
  book           FK, on_delete=CASCADE
  page           int
  selected_text  text          the text as captured, for search and display
  position_data  JSON          D1, versioned
  colour         short choice  yellow | green | blue | pink
  note           text, blank   a note is an attribute of a highlight...
  created_at, updated_at
  index: (user, book, page)

PageNote                       ...and this is one that is not
  user, book, page
  body           text
  created_at, updated_at
```

`PageNote` exists so scanned books (D2) still support notes. Without it, "add a
note" is unavailable on exactly the books most likely to need one.

---

## API

```text
GET    /api/books/{id}/bookmarks
POST   /api/books/{id}/bookmarks
PATCH  /api/books/{id}/bookmarks/{bid}/
DELETE /api/books/{id}/bookmarks/{bid}/

GET    /api/books/{id}/highlights          ?page= for the visible range
POST   /api/books/{id}/highlights
PATCH  /api/books/{id}/highlights/{hid}/   colour, note
DELETE /api/books/{id}/highlights/{hid}/

GET    /api/books/{id}/notes
POST   /api/books/{id}/notes
PATCH  /api/books/{id}/notes/{nid}/
DELETE /api/books/{id}/notes/{nid}/
```

Every one of these filters on `user=request.user` **and** re-checks that the
user may read the book. Two separate checks, because they answer different
questions: "is this mine?" and "am I still allowed to see the book it is on?" —
sharing can be revoked after an annotation is created.

Fetch highlights for the visible page range rather than the whole book; a
heavily annotated 900-page book is a lot of JSON to hand a phone.

---

## Frontend work

- Selection → floating toolbar → highlight, choose colour, attach note.
- Highlight overlay layer positioned from `position_data`, re-projected on
  every zoom or resize via `viewport.convertToViewportPoint()`.
- Annotations sidebar: bookmarks, highlights, notes; click to jump.
- Touch selection, which is where text selection is hardest. (§39 calls tablet
  a primary reading target; that was later set aside — see the README.)
- Deletion with undo rather than a confirm dialog.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Highlights drift after a zoom change | User-space quads (D1); test at 50%, 100%, 400% and after a window resize. |
| Position format needs changing after launch | Version field from the first write. |
| Annotations lost when a Drive file goes missing | FKs point at `Book` (D3); test it explicitly. |
| Overlay repaint janks on scroll | Project once per zoom change, not per scroll frame. |
| Another user reads private annotations | Object-level permission tests per endpoint (§29). |

## Acceptance (PRD §45)

Criteria **15** (bookmarks), **16** (highlights and notes), **22** (independent
per reader), **24** (no access to another user's private annotations).

Add: a highlight created at 100% zoom lands correctly at 400% and on a phone;
marking a source unavailable leaves every annotation intact.

**Rough size:** medium. The data model is small; the selection and overlay
handling is the work.
