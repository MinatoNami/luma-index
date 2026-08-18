# Phase 4 — PDF reader

**Goal:** a PDF.js reader that stays responsive on a 400 MB scanned book on a
tablet, and resumes where you left off on another device.

**Depends on:** Phases 2–3.

---

## Decide before writing code

### D1. How PDF bytes reach the browser — **the load-bearing decision**
PDF.js issues HTTP **Range** requests so it can render page 1 without
downloading the file. Two consequences:

1. The content endpoint **must** honour `Range` and return `206 Partial
   Content` with `Accept-Ranges: bytes`. Without it PDF.js falls back to
   fetching the whole file first, and a 400 MB book takes minutes to open.
2. **Streaming through gunicorn ties up a sync worker for the whole
   download.** Three workers and three large reads and the instance is wedged —
   including for the health check.

| Option | How | Verdict |
| --- | --- | --- |
| Stream from the Django view | `FileResponse` + manual range handling | Simple, and the wedging problem above is real. |
| **Internal redirect** (recommended) | Django authorizes, returns `X-Accel-Redirect` to a proxy-internal path; the proxy serves the file and handles ranges | Worker is free in milliseconds. |
| ASGI + async streaming | uvicorn worker for this route | Frees the worker but still copies bytes through Python. |

Recommendation: **internal redirect.** Caddy has no `X-Accel-Redirect`, so
either add a small nginx sidecar for cached-file delivery or use Caddy's
`handle /internal/*` with a signed, short-lived path that only Django can mint.

Whichever is chosen, the rule from PRD §18 and §29 is absolute: **Django
authorizes every request before a single byte moves, and the cache directory is
never a public static root.**

### D2. Reading-progress conflict resolution
PRD §19 and §21 require per-user progress and cross-device resume but never say
what happens when two devices write. Last-write-wins silently rewinds a reader
whose phone was left open on page 3.

Recommendation: client sends its own `updated_at`; the server ignores any
update older than the stored value. Deterministic, needs no coordination, and
handles the left-a-tab-open case. Write the rule down in the API docs — an
undocumented conflict rule gets "fixed" by the next person.

### D3. What "position" means
A page number alone jumps around at different zoom levels in continuous scroll.

Recommendation: store `page` plus a **fraction of the way through that page**
(0.0–1.0), not a pixel offset. Survives zoom, window resize, and phone-to-
desktop. Pixel offsets do not, and PRD §21 asks for exactly this property.

### D4. Shipping PDF.js
The artifact CSP forbids CDNs, and so should the app. Bundle `pdfjs-dist`,
serve the worker from your own origin, and — if CJK books matter — ship
`cMaps` too. A reader that silently renders blank pages for Japanese text is a
confusing bug to chase later.

---

## Data model

```text
ReadingProgress
  user            FK, on_delete=CASCADE
  book            FK, on_delete=CASCADE
  page            int
  page_fraction   float 0..1   (D3)
  percentage      float        denormalised for library cards
  last_opened_at
  updated_at                   client-supplied; drives D2
  unique_together: (user, book)

UserSettings
  user            OneToOne, on_delete=CASCADE
  theme           light | dark | system
  reader_mode     continuous | single
  zoom            float or 'fit-width' | 'fit-page'
  sidebar_open    bool
  preferences     JSON for everything not worth a column yet
```

`ReadingProgress` is the hottest table in the app — written every few seconds
per active reader. Index `(user, book)` (the unique constraint does this) and
`(user, last_opened_at)` for Continue Reading.

---

## API

```text
GET  /api/books/{id}/content        Range-aware, authorized, 206
GET  /api/books/{id}/outline        PDF table of contents, cached
GET  /api/books/{id}/progress
PUT  /api/books/{id}/progress       idempotent upsert, D2 conflict rule
GET  /api/reader/settings/
PATCH /api/reader/settings/
```

Progress writes are debounced client-side (~5s, and on page change, blur, and
`visibilitychange`) — PRD §21 asks for throttling, and `pagehide` is what
actually catches a closing tab on mobile Safari.

---

## Frontend work

Required features (PRD §20): continuous scroll, single-page mode, prev/next,
jump to page, page/total, percentage, zoom, fit width, fit page, fullscreen,
page thumbnails, outline, text selection, in-document search, keyboard
navigation, touch navigation, restore position.

Performance rules (PRD §26) — decide these into the architecture, not as a
later optimisation:

- Virtualise the page list; render only visible and near-visible pages.
- **Destroy canvases for pages scrolled out of range.** Retaining every page
  canvas is the single fastest way to crash a tablet.
- Cancel superseded `RenderTask`s on fast scroll instead of queueing them.
- Render thumbnails lazily at low scale, in their own queue.
- Cap device pixel ratio on mobile; a 3× canvas of an A4 page is large.

Accessibility (PRD §40): visible focus, labelled controls, no hover-only
actions, 44px touch targets, `prefers-reduced-motion` honoured.

Scanned PDFs (PRD §27): when `has_text_layer` is false, disable search and say
why rather than returning zero results silently.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| One big download blocks every worker | D1 internal redirect. Test with a 300 MB+ book and concurrent readers. |
| Tablet crashes on a long book | Canvas eviction and a virtualised page list, tested on a real device. |
| Progress jumps backwards | D2 rule, with a test for the stale-write case. |
| Missing `Range` support goes unnoticed in dev | Assert `206` and `Accept-Ranges` in an integration test — small local PDFs hide this. |
| Blank pages for CJK books | Bundle cMaps (D4). |

## Acceptance (PRD §45)

Criteria **12** (read via PDF.js), **13** (progress syncs across devices),
**14** (text search when a layer exists), **28** (large PDFs usable without
excessive memory).

Add: a 300 MB book opens to page 1 in seconds, not after a full download;
memory stays flat while scrolling 200 pages; two devices resume consistently.

**Rough size:** large, and mostly frontend. The reader is where the product is
either good or not.
