# Phase 5 — Bookmarks, highlights, notes

**Goal:** private, per-user annotations that survive zoom changes, resizes, and
moving between a phone and a desktop — without ever modifying the PDF.

**Depends on:** Phase 4 (the reader and its text layer).

## Decisions

**Highlight anchoring — decided before the first highlight was stored.** §23
says "store positions independently from viewport pixels" and stops there. This
is the one schema in the project that is genuinely painful to change later: once
users have highlights, a format change means migrating coordinates you can no
longer recompute, because the mapping depended on the viewport that produced
them. Each highlight stores:

```jsonc
{
  "v": 1,                       // schema version, from the very first write
  "page": 42,                   // 0-indexed
  "quads": [                    // PDF user space, origin bottom-left
    { "x1": 72.0, "y1": 640.2, "x2": 288.4, "y2": 652.8 }
  ],
  "text_offsets": { "start": 1840, "end": 1902 }
}
```

- **PDF user space, not screen pixels,** converted with
  `viewport.convertToPdfPoint()`. A point in user space means the same thing at
  any zoom, on any screen, forever.
- **Quads, not a bounding box.** A selection spanning three lines is three
  rectangles; one box would highlight the margins between them.
- **A version field from day one,** because adding one later means guessing what
  unversioned rows meant.
- **Character offsets as a secondary anchor,** which can often re-locate a
  selection when a re-scan changes the geometry and coordinates cannot.

**Scanned books get bookmarks and page notes, not text highlights.** §27 books
have no selectable text, so text-anchored highlights are impossible. `PageNote`
exists precisely so "add a note" is not unavailable on the books most likely to
need one. OCR is deferred (§27, §42); a later OCR pass adds a text layer without
invalidating anything stored now.

**Annotations hang off `Book`, never `BookSource`.** §35 says failures must not
destroy reader metadata. A missing file marks the *source* unavailable; the book
and everything written on it stays. Get the FK targets right and this is
automatic.

A note is an attribute of a highlight (`Highlight.note`), while a `PageNote` is
its own row — the two are not the same thing.

## Rules that carried

- **Every annotation endpoint makes two checks:** `user=request.user`, *and*
  that the user may still read the book. They answer different questions —
  "is this mine?" and "am I still allowed to see what it is on?" — and sharing
  can be revoked after an annotation is created.
- **Fetch highlights for the visible page range,** not the whole book. A heavily
  annotated 900-page book is a lot of JSON to hand a phone.
- **Project the overlay once per zoom change, not per scroll frame,** via
  `viewport.convertToViewportPoint()`.
- Highlights are tested at 50%, 100% and 400% and after a resize, because drift
  is the failure that matters and it is invisible at one zoom level.
