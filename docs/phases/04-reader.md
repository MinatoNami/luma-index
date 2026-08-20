# Phase 4 — PDF reader

**Goal:** a PDF.js reader that stays responsive on a large scanned book and
resumes where you left off on another device.

**Depends on:** Phases 2–3.

## Decisions

**How PDF bytes reach the browser — the load-bearing one.** PDF.js issues HTTP
`Range` requests so it can render page 1 without downloading the file, so the
content endpoint **must** honour them and return `206` with `Accept-Ranges:
bytes`; without it PDF.js fetches the whole file first and a 400 MB book takes
minutes to open. The risk is the other side of that: streaming through gunicorn
occupies a worker for the whole download, and three sync workers with three
large reads wedges the instance, health check included.

An internal redirect (`X-Accel-Redirect`) was the recommendation, which would
free the worker in milliseconds. What was built instead is Django streaming with
threaded workers, so a long download costs a thread rather than a process. That
is enough at this scale and left as a tuning question — see the README's known
gaps. Caddy has no `X-Accel-Redirect` anyway, so the redirect route would need a
signed short-lived path only Django can mint.

Whichever is used, the rule from §18 and §29 is absolute: **Django authorizes
every request before a single byte moves, and the storage directory is never a
public static root.**

**Reading-progress conflicts resolve by client timestamp.** §19 and §21 require
per-user progress and cross-device resume but never say what happens when two
devices write, and last-write-wins silently rewinds a reader whose phone was
left open on page 3. The client sends its own `client_updated_at` and the server
ignores anything older than what is stored. Deterministic, needs no
coordination.

**Position is a page plus a fraction of the way through it** (0.0–1.0), not a
pixel offset. A page number alone jumps around at different zoom levels in
continuous scroll; a pixel offset does not survive zoom, resize, or
phone-to-desktop. §21 asks for exactly this property.

**PDF.js is bundled, not loaded from a CDN.** `pdfjs-dist` with the worker
served from our own origin, and cMaps shipped if CJK books matter — a reader
that silently renders blank pages for Japanese text is a confusing bug to chase
later.

## Performance rules

Architecture, not later optimisation (§26):

- Virtualise the page list; render only visible and near-visible pages.
- **Destroy canvases for pages scrolled out of range.** Retaining every page
  canvas is the fastest way to crash a tablet.
- Cancel superseded `RenderTask`s on fast scroll instead of queueing them.
- Render thumbnails lazily at low scale, in their own queue.
- Cap device pixel ratio on mobile; a 3× canvas of an A4 page is large.

`ReadingProgress` is the hottest table in the app, written every few seconds per
active reader. Writes are debounced client-side (~5s, and on page change, blur
and `visibilitychange`); `pagehide` is what actually catches a closing tab on
mobile Safari. Index `(user, book)` — the unique constraint does it — and
`(user, last_opened_at)` for Continue Reading.

When `has_text_layer` is false (§27), search is disabled with an explanation
rather than returning zero results silently.
