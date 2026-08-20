# LumaIndex

A self-hosted PDF library and reader for a household or a small team.

Upload your PDFs, organise them in folders, and read them in the browser — on a
desktop, a tablet, or a phone. Books are private until you choose to share one,
and everyone who reads a book keeps their own place in it along with their own
bookmarks, highlights, and notes.

It runs as five containers on one Ubuntu machine — PostgreSQL, Django, Nuxt,
Caddy and a background worker — reachable over
[Tailscale](https://tailscale.com) and nothing else.

> **On the PRD.** [`lumaindex-prd.md`](lumaindex-prd.md) is the original
> specification and still governs the reader, sharing, and annotation
> behaviour. Its storage chapters do not: it assumed Google Drive was canonical
> storage, that was built, and it was then replaced by direct uploads. Where the
> two disagree about *storage*, this README is current.

---

## What it does

| | |
| --- | --- |
| **Upload** | Drag PDFs in from your computer — onto the page, or straight onto a folder. Large files are sent in pieces and resume where they left off if the connection drops. A ZIP has its folder structure rebuilt on import. Identical files are stored once. |
| **Organise** | Folders you create, rename, and delete. Drag items onto a folder to move them, or use the picker on any row. Tick several — shift-click for a run — and move, trash, favourite or collect them in one go. Each folder wears a mosaic of the covers inside it. Sort either by name, date added, last modified, size, or type. Deleting goes to a trash you can restore from — sortable too, including by when you deleted it. |
| **Read** | A PDF.js reader: continuous scroll or single page, zoom, text selection, search within the book, an outline sidebar, page thumbnails. The toolbar gets out of the way as you read forward and comes back when you scroll up. A book you have opened before opens from cache. |
| **Resume** | Your place is saved as you read and picked up on any other device. |
| **Annotate** | Bookmarks, highlighted passages in four colours, notes on a highlight, and page notes for scans with no text layer. |
| **Collect** | Star a book as a favourite, or gather books into collections that cut across folders. |
| **Share** | Mark a book shared and anyone signed in can read it — while keeping their own place and their own notes. |
| **On a phone** | Add it to the Home Screen and it runs without browser chrome. Labels give way to icons on a narrow screen, and the reader's secondary controls move into one menu rather than crowding the bar. |

## What it deliberately does not do

No EPUB, no OCR, no AI features, no public sign-up, no anonymous reading, and no
sharing with named individuals or groups — sharing is all-or-nothing within the
instance. These are the PRD's non-goals (§42) and remain so.

---

## How it works

```text
                    Your devices, on the tailnet
                              │
                              │  https://luma.your-tailnet.ts.net
                              ▼
                     ┌─────────────────┐
                     │ tailscale serve │  terminates TLS with a real
                     └────────┬────────┘  certificate for the MagicDNS name
                              │  http, loopback only
                              ▼
                     ┌─────────────────┐
                     │      Caddy      │  one origin, so no CORS and the
                     └───┬─────────┬───┘  session cookie stays SameSite=Lax
             /api,/admin │         │ everything else
                         ▼         ▼
              ┌──────────────┐  ┌────────┐
              │ Django + DRF │  │ Nuxt 3 │
              │              │  │ PDF.js │
              │ auth         │  └────────┘
              │ authorization│
              │ uploads      │
              │ PDF delivery │
              └───┬──────┬───┘
                  │      │
        ┌─────────▼─┐  ┌─▼──────────────────────────┐
        │PostgreSQL │  │ library/     uploaded PDFs │ ← canonical, back this up
        │           │  │ thumbnails/  covers        │ ← regenerable
        └───────────┘  │ staging/     in-flight     │ ← scratch
              ▲        └────────────────────────────┘
              │
     ┌────────┴────────┐
     │  ingest worker  │  extracts ZIPs, probes page counts,
     └─────────────────┘  detects text layers, renders covers
```

**Nothing is published beyond `127.0.0.1`.** Caddy binds to loopback and
`tailscale serve` is the only way in, so the app is never exposed to the LAN or
the internet — while still getting a real TLS certificate, which is what makes
`Secure` cookies work.

### What happens when you open a book

1. The browser asks Django for the book. Django checks you may read it — you own
   it, or its owner shared it — and returns 404 if not. **404, not 403: a 403
   would confirm the book exists.**
2. PDF.js asks for a byte range rather than the whole file. Django answers
   `206 Partial Content`, so a 500-page book opens on page one instead of after
   a full download.
3. Pages render to canvases as they come near the viewport, and their canvases
   are thrown away as they leave. No more than a handful hold pixels at once —
   a 535-page book stays around 40 MB rather than growing without limit.
4. Your position is reported as you scroll, debounced, and written to the server
   so another device can pick it up.

### What happens when you upload a ZIP

The request stores the archive and returns immediately; extracting a few hundred
books would time out. The ingest worker picks it up, validates every entry
before writing anything, rebuilds the folder structure, and then probes each PDF
for its page count, whether it has a text layer, and a cover image.

Archives are treated as hostile: entries that escape the target directory,
symlinks, compression bombs, and entries lying about their size are all rejected
before a byte is written.

---

## Data model

```text
Folder ──┐
         ├── Book ──── BookSource ──── a file in library/
         │     │
         │     ├── ReadingProgress ┐
         │     ├── Bookmark        ├─ one set per reader, private
         │     ├── Highlight       │
         │     └── PageNote        ┘
```

Three shapes carry the design:

- **`Book` is separate from `BookSource`.** The reader and library never touch
  the file directly, so a replaced scan — or another storage provider — can
  change the bytes without disturbing anything written about the book.
- **Annotations hang off `Book`, never `BookSource`.** A file going missing
  flags the source and leaves every note intact.
- **Storage is content-addressed.** A file's SHA-256 is its identity and its
  path, so uploading the same PDF twice stores one copy and a retried import
  costs no extra disk. A file is deleted only once no book references it.

Deleting is a **trash**. An uploaded PDF may be the only copy its owner has, so
deletion is reversible and destroying it is a separate, explicit step.

**The frontend is typechecked and tested in CI**, which it was not. `npm run
typecheck` had only ever been run by hand and had collected fourteen errors —
one of them a real bug, where opening a highlight from the notes list passed an
id where a click position was expected, so `activeHighlightRecord` looked for
`.id` on a number, found nothing, and the popover's `v-if` silently never
rendered. Clicking a highlight in the sidebar jumped to the page and then did
nothing at all.

**`color-scheme` follows the chosen theme, not the machine.** It was declared
once, as `light dark` on bare `:root`, which is right for *follow my system* and
wrong for the other two — and `color-scheme` is what native controls read, so
forcing the app light on a machine set to dark left black checkboxes sitting in
a white page. Two attribute-selector overrides tie them together.

**The theme button toggles against what is on screen.** It used to cycle
light → dark → system, which meant one press in three changed nothing you could
see: with the setting on *system* and the machine set to light, the app already
looked light, so choosing *light* moved the stored value and not a pixel. It
appeared to need two presses. The decision is now a pure `nextTheme()` in
`useSettings`, tested directly, and *system* lives in Settings where choosing it
is deliberate rather than somewhere you land mid-cycle.

**Accessibility is audited, not assumed.** PRD §40 lists seven requirements and
only contrast had ever been checked. An axe-core pass over every page, at
desktop and phone width, now comes back clean against WCAG 2.1 AA and 2.2 AA —
it did not before. What it found was mostly real: no `lang` on `<html>`
anywhere, a filter row marked up as a `tablist` when it has no tabpanels and no
arrow-key model (a promise to a screen reader that nothing kept), the reader's
page area scrolling without being focusable so a keyboard user could reach every
button and still not move the page, and no `main` landmark in the reader at all.

Two of its findings were layout bugs rather than markup ones. Row checkboxes
were 16px against WCAG 2.2's 24px floor, and on a book card the favourite star
and the select checkbox were both positioned in the top-left corner — the
checkbox above it with a `z-index`, so on a phone, where selection is always
visible rather than revealed on hover, it covered the star completely and a book
could not be favourited from its card at all. Selection now owns the left
corner and the two per-item actions sit together on the right.

**A book is downloaded once.** `/content` answers with the file's storage key
as its ETag, which content addressing makes both free and exact — the key is
the SHA-256 of the bytes, so it cannot claim "unchanged" about a file that
changed. Re-opening a book then costs a 304 instead of the whole download: 25 MB
became 0 on the instance this was measured on. The same strong validator is
what lets `If-Range` resume a partial download rather than start it again, and
a range conditional on a version the server no longer has is answered in full
rather than letting a client stitch new bytes onto an old prefix.

**A large upload is sent in pieces**, in `library/chunked.py`, and what it
becomes at the end depends on what it is: a PDF goes to `store_upload`, a ZIP
is handed to the ingest worker as a batch. Sending an archive down the PDF path
rejects it for not being a PDF *after every byte has arrived*, which is exactly
what chunking did to ZIPs when it first shipped. One multipart
POST is all-or-nothing, and on a link that drops every few minutes a 600 MB
file never lands — each attempt starts again from zero. The server's `received`
counter, which is the size of the bytes actually on disk rather than anything a
client claims, is the only thing that decides where the next chunk goes. A
chunk arriving twice is behind that mark and refused; one arriving early would
leave a hole and is refused too; both replies carry the real offset so a client
corrects itself in one round trip instead of guessing. Completion hands the
assembled file to the same `store_upload` a small file goes through, so the
magic-byte check, size limit, quota accounting and deduplication have no second
path to drift out of step with.

**A password reset answers 204 even when the mail fails.** The endpoint
already refused to say whether an address had an account; sending inside the
request quietly undid that, because a 500 from a refused SMTP handshake says
"this address exists" exactly as loudly as a 404 would, and says it only for
the addresses that do. Send failures are swallowed, logged at ERROR with the
exception type but never the address, and `manage.py check_email` exists so a
misconfigured relay can be found without locking anyone out to find it. TLS or
SSL follows the port unless you say otherwise, and `EMAIL_TIMEOUT` is set
because password reset sends inside a request and smtplib's default wait is
measured in minutes.

**Backups land on the machine that runs the deploy script**, never only on the
server — a backup on the host it backs up survives everything except the
failure you are afraid of. The two halves are treated differently because they
fail differently: the database is snapshotted per run, while the library is
mirrored, since a file named after the SHA-256 of its own contents cannot hold
anything else and so has nothing to snapshot. Only new files travel. The mirror
is additive — a file missing on the server is either a book somebody deleted or
a book somebody lost, and nothing can tell those apart. `deploy.sh verify`
rehashes every file against its own name, which costs nothing to keep honest
because the expected hash *is* the filename: no separate checksum list to drift
out of date.

**The trash can empty itself**, and does not unless told to. `TRASH_RETENTION_DAYS`
is 0 by default, because this is the only code that destroys a file nobody
asked it to destroy and storage here is canonical — the PDF in the trash may be
its owner's only copy, and the two-step delete exists to protect exactly that.
Turned on, it stops the trash being where quota goes to hide. The sweep runs in
the ingest worker, hourly and bounded, and refuses to delete a folder that
still holds a live item: `Folder.trash()` cannot leave one behind, but a cascade
delete does not check and the cost of being wrong is somebody's only copy.
`manage.py empty_trash --dry-run` shows what would go.

**Sorting is one vocabulary across three listings** (`library/sorting.py`).
A folder has a `name`, a book has a `title`, and only one of them has a size,
so left alone each listing would grow its own words for the same idea.
`?sort=name` means the same thing everywhere, and asking folders for a column
they do not have falls back to plain alphabetical rather than to a direction
nobody chose. Ordering by type is not in there: folders and books come back as
separate lists, so "files first" is a question about which block to draw first,
not one for the database.

**A selection is acted on in one request**, through `library/bulk.py`. Every
operation there is partial by design: an item that cannot be acted on is
skipped with a reason and the rest still go through, so moving forty books into
a folder that already holds one of their names reports the collision instead of
leaving the user to work out which thirty-nine arrived. Ids belonging to
someone else are filtered out rather than rejected — saying which of a hundred
ids was refused would confirm the row exists.

**Storage is charged per account**, in `library/quota.py`. What counts is the
distinct files an account's books point at, trash included. Distinct, because
the same PDF filed in two folders is two books over one blob and billing it
twice charges for disk nobody used; per-account rather than shared, because
whether an upload was free would otherwise depend on whether a stranger
uploaded it first — arbitrary, and a disclosure that a file already exists.
Trashed books count, which is also what gives emptying the trash a point. The
limit is `LUMA_DEFAULT_USER_QUOTA_BYTES`, unlimited by default and overridable
per user in the admin; it is a separate refusal from the free-disk floor, since
running out of disk is everyone's problem and running out of quota is one
library's.

**Folders have no picture of their own**, so they borrow one. The API sends up
to four book ids per folder and the browser tiles the same per-book covers it
already shows in the grid — there is no composited folder image anywhere, and so
nothing to invalidate when a folder's contents change. A stored composite would
have to be regenerated on every add, move, trash, restore, delete and cover
render, up the ancestor chain, and would still show the wrong picture until the
worker caught up. Lookahead stops one level down: a folder holding only
subfolders — what every ZIP import produces at its root — takes one cover from
each child in turn, so it summarises what is beneath it instead of impersonating
its own first child. See `library/previews.py`.

---

## Quick start

Locally, with hot reload:

```bash
cp .env.example .env && docker compose -f compose.yaml -f compose.dev.yaml up --build
```

To a server — one-time preparation, then deploys:

```bash
cp deploy/deploy.env.example deploy/deploy.env   # where to deploy
```

```bash
./deploy/deploy.sh bootstrap                      # docker, ufw, tailscale serve
```

```bash
cp .env.example .env && $EDITOR .env              # fill in every CHANGE_ME
```

```bash
./deploy/deploy.sh env:push && ./deploy/deploy.sh
```

Deploys build on the server, flip a symlink only after the build succeeds, gate
on a readiness check, and roll back automatically if the new release never
becomes healthy. Full walkthrough, backups, and troubleshooting in
[docs/deployment.md](docs/deployment.md).

---

## Known gaps

Things built but unproven, or deliberately missing.

### Unverified

Creating, removing and recolouring highlights, single-page navigation, and
covers surviving a refresh were all unverified here and have since been
confirmed working in a real browser. Covers surviving a refresh now has a test
that fails if the fix is removed, rather than resting on having looked once.

The reader itself — its render window, canvas budget and search — has no
automated coverage. Those bugs were all about what a browser does with a canvas
under `requestAnimationFrame`, which is the one thing this environment cannot
run.

Every page has now been measured at 375px and none overflows horizontally,
with each control at least 32px. That was not true before: the library's top
bar ran 150px past a phone screen, which made the *document* wider than the
viewport and left everything on it looking misaligned rather than merely
cramped. The reader's bar ran 72px over and crushed its back button to 16px.

It can be added to an iOS Home Screen and runs without Safari's chrome — a web
app manifest with `display: standalone`, `viewport-fit=cover`, and safe-area
insets wherever the layout meets an edge. Those live in the pages' own scoped
styles rather than a global sheet, because a scoped selector carries an
attribute and outranks a global rule for the same class; the first attempt put
them in `main.css` and they never applied to anything. In the reader the top
inset belongs to the shell rather than the bar, so the bar can collapse to
nothing when it hides — `overflow: hidden` clips at the padding box, so a bar
collapsed into its own padding still paints its contents there.

There is no service worker, so it needs the network (and the tailnet) like any
other page; nothing is available offline.

Measured at a phone viewport in a desktop browser, and since used for real as a
Home Screen app on an iPhone 13 — which is where the layout was actually
settled. The desktop viewport missed three things that only the device showed:
the safe-area rules silently losing to scoped styles, a collapsed bar still
painting its own contents inside its padding, and a bar of nine controls that
fitted the width but read as one undifferentiated row of glyphs. Overflow
arithmetic is not the same as looking at it.

PRD §39 treats tablet as a primary reading target; in practice it is not one
for this instance, so tablet-specific testing is not tracked as outstanding
work.

No real relay has been used from here. Delivery was exercised end to end
against a local SMTP sink — the message arrived with the right sender,
recipient and subject — and the failure paths were driven directly: a refused
connection, and a relay that will not accept credentials. What has not been
tried is a provider that wants an app password or rejects the From domain,
which is exactly what `check_email` is for.

This is deployed, on an Ubuntu host reached over Tailscale, alongside unrelated
services — which is why `bootstrap.sh` was skipped there and its three jobs
done by hand (see [the deployment notes](docs/deployment.md)). Running it for
the first time found two bugs that had never executed: a `set -e` abort from a
trailing `&&`, and an SSH control-socket path too long for a Unix socket on
macOS. A third was worse — `build` tagged images with the release stamp while
`up -d` resolved the default and started `:latest`, so every deploy after the
first ran the previous code.

`backup`, `verify` and `restore:library` have all run against that server. The
library mirror was exercised with a real blob: the bytes came back
byte-identical over the `tar`-through-`docker exec` stream with the hash
matching its own name, a single flipped byte is caught, and the hash check
refuses to run at all when no hashing tool is present rather than passing by
comparing nothing to nothing.

What has not been tried is a restore onto an empty server. The parts are
proven; the drill as a whole is not.

Trash retention is off on this instance, so its sweep has never destroyed
anything here. The sweep itself, its refusal to touch a folder holding live
items, and the worker running it on a pass are covered by tests; what has not
been watched is the hourly cadence over a long-running worker, since the tests
drive a single pass. `manage.py empty_trash --dry-run` has been run against the
real trash and reported what it would do.

The reason they could not be checked from the development tooling is worth
keeping: the preview pane cannot render PDFs at all. PDF.js drives its render
loop with `requestAnimationFrame`, and that pane runs with
`document.visibilityState: 'hidden'`, where rAF never fires — so a render never
completes and nothing downstream of it runs. **Anything needing pixels on a page
has to be checked in a real browser.**

### Missing for now

| What | Consequence |
| --- | --- |
| **Sharing with named people or groups** | §16 keeps this to private or shared-with-everyone-signed-in. The richer model is §43 future work and would change `library/permissions.py` alone. |

### Open question

**Whether large reads should bypass gunicorn.** Byte ranges work, so a big book
opens quickly, but a long download still occupies a worker for its duration.
Less pressing since the server moved to threaded workers — it now costs a
thread rather than a process — but a genuinely large library served to several
readers at once would still be better off with the bytes never entering
Python.

---

## Status

| Phase | State |
| --- | --- |
| 1 — Platform, auth, deployment | Built |
| 2 — Uploads, folders, storage | Built |
| 3 — Library | Built |
| 4 — PDF reader | Built |
| 5 — Bookmarks, highlights, notes | Built |
| 6 — Sharing | Built |
| 7 — Hardening | Built |

457 backend tests, including a 64-case object-level permission matrix, and 48
frontend tests over the logic that has actually broken here — selection
ranges, cover loading states, sort labels.

---

## Repository

```text
backend/            Django + DRF
  accounts/           users, sessions, password reset, preferences
  library/            folders, books, storage, uploads, reader data, sharing
                      quota.py, retention.py, chunked.py, sorting.py, previews.py
  api/                routing, health probes, OpenAPI schema
  common/             logging with credential redaction, advisory locks
frontend/           Nuxt 3 — library browser, reader, settings
  tests/              Vitest over the logic that has actually broken here
caddy/              reverse proxy configuration
deploy/             bootstrap.sh and deploy.sh
docs/               deployment guide and per-phase design records
scripts/            check-contrast.py — verifies the palette against WCAG AA
```

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Nuxt 3, Vue 3, TypeScript, PDF.js |
| Tests | pytest + pytest-django, Vitest + Vue Test Utils, ruff, vue-tsc, ShellCheck |
| Backend | Django 5.2 LTS, Django REST Framework |
| Database | PostgreSQL 16 |
| Documents | pypdfium2 (Apache-2.0), Pillow |
| Deployment | Docker Compose, Caddy, Ubuntu, Tailscale |

No Redis and no Celery. Background work — ZIP extraction, probing, cover
rendering — runs in a worker that claims jobs with a PostgreSQL advisory lock,
which the PRD (§36) asks for until an async workload actually justifies more.

## Security

- One origin for app and API, so no CORS and a `SameSite=Lax` session cookie.
- Sessions are HttpOnly; no token is ever handed to JavaScript.
- CSRF is enforced on every unsafe method **including anonymous ones** — DRF
  exempts APIViews by default, which leaves login open to CSRF.
- Authentication is rate-limited per address *and* per targeted account.
- Authorization is decided server-side by one function and covered by a
  permission matrix. An admin gets no extra read access through the app.
- Uploads are sniffed for `%PDF-` rather than trusted by extension, and archives
  are validated entry by entry before anything is written.
- Credentials are redacted from logs by a filter rather than by convention.

## Documentation

- [docs/deployment.md](docs/deployment.md) — deploying, backups, the restore
  drill, troubleshooting
- [docs/phases/](docs/phases/) — the design record for each phase, including the
  six decisions that were expensive to reverse and how each was settled
- [lumaindex-prd.md](lumaindex-prd.md) — the original specification
