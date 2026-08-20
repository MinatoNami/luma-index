# LumaIndex

A self-hosted PDF library and reader for a household or a small team.

Upload your PDFs, organise them in folders, and read them in the browser — on a
desktop, a tablet, or a phone. Books are private until you share one, and every
reader keeps their own place, bookmarks, highlights, and notes.

Five containers on one Ubuntu machine — PostgreSQL, Django, Nuxt, Caddy, and a
background worker — reachable over [Tailscale](https://tailscale.com) and
nothing else.

> [`lumaindex-prd.md`](lumaindex-prd.md) is the original spec and still governs
> the reader, sharing, and annotations. Its storage chapters do not: they
> assumed Google Drive was canonical storage, which was built and then replaced
> by direct uploads. Where the two disagree about storage, this README is
> current.

---

## What it does

| | |
| --- | --- |
| **Upload** | Drag PDFs onto the page or onto a folder. Large files go in pieces and resume if the connection drops. A ZIP has its folder structure rebuilt. Identical files are stored once. |
| **Organise** | Folders you create, rename, and delete. Drag to move, or use the row picker. Tick several — shift-click for a run — and move, trash, favourite or collect them at once. Folders wear a mosaic of the covers inside them. Sort by name, date added, last modified, size, or type. |
| **Read** | PDF.js: continuous scroll or single page, zoom, text selection, in-book search, outline sidebar, page thumbnails. The toolbar hides as you read forward and returns when you scroll up. |
| **Resume** | Your place is saved as you read and picked up on any other device. |
| **Annotate** | Bookmarks, highlights in four colours, notes on a highlight, and page notes for scans with no text layer. |
| **Collect** | Star a favourite, or gather books into collections that cut across folders. |
| **Share** | Mark a book shared and anyone signed in can read it — keeping their own place and notes. |
| **On a phone** | Add to the Home Screen and it runs without browser chrome. Labels become icons on narrow screens; the reader's secondary controls fold into one menu. |

**Deliberately not:** EPUB, OCR, AI features, public sign-up, anonymous reading,
or sharing with named people or groups — sharing is all-or-nothing within the
instance. These are the PRD's non-goals (§42).

---

## How it works

Four diagrams, because these four things fail and change independently.

### Getting in

```text
        your devices, on the tailnet
                    │
                    │  https://<name>.ts.net:8443
                    ▼
           ┌─────────────────┐
           │ tailscale serve │   terminates TLS with a real certificate
           └────────┬────────┘   for the MagicDNS name
                    │  plain http, 127.0.0.1 only
                    ▼
           ┌─────────────────┐
           │      Caddy      │   one origin, so no CORS and the session
           └──┬───────────┬──┘   cookie stays SameSite=Lax
   /api /admin│           │everything else
              ▼           ▼
        ┌──────────┐  ┌────────┐
        │  Django  │  │ Nuxt 3 │
        │  + DRF   │  │ PDF.js │
        └──────────┘  └────────┘
```

Nothing is published beyond `127.0.0.1`: Caddy binds to loopback and
`tailscale serve` is the only way in, so the app is never exposed to the LAN or
the internet — while still getting a real certificate, which is what makes
`Secure` cookies work.

### Where the data sits

```text
        ┌──────────────┐
        │ Django + DRF │  auth · authorization · uploads · PDF delivery
        └───┬──────┬───┘
            ▼      ▼
  ┌────────────┐  ┌───────────────────────────────────────────┐
  │ PostgreSQL │  │ library/     uploaded PDFs     canonical  │ ← back this up
  │            │  │ thumbnails/  covers            derived    │ ← re-renderable
  └────────────┘  │ staging/     uploads in flight scratch    │ ← discardable
                  └───────────────────────────────────────────┘
```

Only the first two matter for a restore, and only the first cannot be rebuilt.

### What happens in the background

```text
  ┌───────────────┐   claims each job with a PostgreSQL advisory lock,
  │ ingest worker │   so a second worker — or a manual command — is
  └───────────────┘   safe to run alongside it

    on an upload  ·  extract a ZIP, rebuild its folders
                  ·  probe page count, detect a text layer
                  ·  render the cover
        hourly    ·  delete expired trash (off by default)
                  ·  drop uploads nobody finished
```

No Redis and no broker: a polling loop with an advisory lock is what PRD §36
asks for until an async workload justifies more.

### How a file gets in

```text
  under 16 MB   one multipart POST ─────────────────────────► stored
  over 16 MB    8 MB chunks ──► staged file ──► assembled ──► stored
  a .zip        staged ────────► ingest worker ────────────► many books
```

All three end at the same `store_upload`, so the magic-byte check, size limit,
quota accounting and deduplication have no second path to drift out of step
with. A ZIP returns immediately rather than being extracted in the request,
because a few hundred books would time out. **Archives are treated as hostile:**
entries escaping the target directory, symlinks, compression bombs, and entries
lying about their declared size are all rejected before a byte is written.

### Opening a book

1. Django checks you may read it — you own it, or its owner shared it — and
   returns **404, not 403**, because a 403 would confirm the book exists.
2. PDF.js asks for byte ranges; Django answers `206`, so a 500-page book opens
   on page one instead of after a full download.
3. Pages render to canvases near the viewport and are thrown away as they leave.
   A 535-page book stays around 40 MB rather than growing without limit.
4. Your position is reported as you scroll, debounced, and saved so another
   device can pick it up.

---

## Data model

What the library is:

```text
  User ──┬── Folder ──── Book ──── BookSource ──── a file in library/
         │                 │
         │                 └── CollectionBook ──── Collection
         └── UserSettings
```

What each reader owns, separately, for the same book:

```text
  (user, book) ──┬── ReadingProgress   where you got to
                 ├── Bookmark          a page you marked
                 ├── Highlight         quad points in PDF user space
                 ├── PageNote          for scans with no text layer
                 └── UserBookState     favourite
```

And three rows that exist only in passing:

```text
  ChunkedUpload   a large file mid-flight, and how much has arrived
  UploadBatch     a ZIP waiting for the worker, and what it made of it
  ShareAudit      who changed a book's visibility, and when
```

Three shapes carry the design:

- **`Book` is separate from `BookSource`,** so a replaced scan — or another
  storage provider — can change the bytes without disturbing anything written
  about the book.
- **Annotations hang off `Book`, never `BookSource`.** A file going missing
  flags the source and leaves every note intact.
- **Storage is content-addressed.** A file's SHA-256 is its identity and its
  path, so the same PDF uploaded twice stores one copy and a retried import
  costs no disk. A file is deleted only once no book references it.

---

## Design notes

Why the code looks the way it does, one line each.

| | |
| --- | --- |
| **Deleting is a trash** | An uploaded PDF may be its owner's only copy, so deletion is reversible and destroying it is a separate step. |
| **Trash expiry is off by default** | `LUMA_TRASH_RETENTION_DAYS=0`. It is the only code that destroys a file nobody asked it to. Turned on, it stops the trash being where quota hides; the sweep refuses to delete a folder still holding a live item. |
| **Quota is charged per account** | The distinct files an account's books point at, trash included. Distinct, so one PDF filed twice is not billed twice; per-account, so whether your upload is free does not depend on a stranger having uploaded it first. `library/quota.py` |
| **A book is downloaded once** | `/content` uses the storage key as its ETag, which content addressing makes free and exact — it cannot claim "unchanged" about changed bytes. Re-opening costs a 304. The same validator lets `If-Range` resume a partial download. |
| **The server's byte count is authoritative** | A chunk arriving twice is behind the mark and refused; one arriving early would leave a hole and is refused too. Both replies carry the real offset, so a client corrects itself in one round trip. `library/chunked.py` |
| **Sorting is one vocabulary** | `?sort=name` means the same thing in every listing, and asking folders for a column they lack falls back to alphabetical rather than to a direction nobody chose. `library/sorting.py` |
| **Bulk actions are partial by design** | An item that cannot be acted on is skipped with a reason and the rest go through. Ids owned by someone else are filtered out, not rejected — naming them would confirm the row exists. `library/bulk.py` |
| **Folders borrow their covers** | The API sends up to four book ids and the browser tiles covers it already has. No composite exists, so nothing needs invalidating when a folder changes. A folder of only subfolders takes one cover from each in turn. `library/previews.py` |
| **Password reset always answers 204** | Even when the mail fails: a 500 from a refused SMTP handshake says "this address exists" only for addresses that do. Failures are logged with the exception type, never the address; `manage.py check_email` is how you find a broken relay. |
| **Gunicorn runs `gthread`, not `sync`** | With sync workers `--timeout` caps the whole request including the upload body, so a large file dies mid-stream. With threads it is a liveness heartbeat. |
| **Backups land on the machine running the deploy** | A backup on the host it backs up survives everything except the failure you fear. The database is snapshotted; the library is mirrored, since a file named after its own hash has nothing to snapshot. |
| **`color-scheme` follows the chosen theme** | Not the machine — it is what native controls read, so forcing the app light on a dark-mode machine otherwise leaves black checkboxes in a white page. |
| **The theme button toggles against what is on screen** | Cycling light → dark → system meant one press in three changed nothing visible. The decision is a pure `nextTheme()` in `useSettings`; *system* lives in Settings, where choosing it is deliberate. |
| **Accessibility is audited, not assumed** | An axe-core pass over every page, at desktop and phone width, comes back clean against WCAG 2.1 AA and 2.2 AA. It did not before: no `lang`, a `tablist` with no tabpanels, an unfocusable reader viewport, no `main` landmark, 16px checkboxes against a 24px floor. |
| **Pixels have to be checked in a real browser** | PDF.js drives rendering with `requestAnimationFrame`, which never fires where `visibilityState` is `hidden` — so headless preview panes render nothing, and canvas dimensions are set before the render is awaited. |

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
./deploy/deploy.sh bootstrap                     # docker, ufw, tailscale serve
```

```bash
cp .env.example .env && $EDITOR .env             # fill in every CHANGE_ME
```

```bash
./deploy/deploy.sh env:push && ./deploy/deploy.sh
```

Deploys build on the server, flip a symlink only after the build succeeds, gate
on a readiness check, and roll back if the release never becomes healthy. Full
walkthrough, backups, and troubleshooting in
[docs/deployment.md](docs/deployment.md).

---

## Known gaps

| Gap | Detail |
| --- | --- |
| **Four reader e2e tests are `fixme`** | `./scripts/e2e.sh` runs real Chromium on the compose network; two tests pass. The four parked ones infer "this page rendered" from canvas dimensions, which PDF.js sets before awaiting the render. The fix is to wait on the reader, which already knows — a change to the component's public surface. Not wired into CI. |
| **A restore onto an empty server** | `backup`, `verify`, `restore:library` and `drill` have all run against the real server, and the library mirror round-trips byte-identical with a flipped byte caught. The parts are proven; the whole drill is not. |
| **No real SMTP relay** | Exercised against a local sink, plus the failure paths (refused connection, rejected credentials). Untried: a provider wanting an app password or rejecting the From domain — which is what `check_email` is for. |
| **Nothing works offline** | No service worker. A stale cache in front of a PDF library is a worse failure than a clear network error. |
| **Trash expiry cadence unwatched** | Off on this instance. The sweep and its refusals are tested, but only as single passes, not as an hourly job over a long-running worker. |
| **No general alerting** | `backup:status` covers backups only. |
| **Sharing with named people or groups** | §16 keeps this to private or shared-with-everyone-signed-in; the richer model is §43, and would change `library/permissions.py` alone. |
| **Whether large reads should bypass gunicorn** | Byte ranges mean a big book opens fast, but a long download still occupies a thread. A large library served to several readers at once would be better off with the bytes never entering Python. |

Tablet is a primary target in PRD §39 but not for this instance, so
tablet-specific testing is not tracked as outstanding.

---

## Status

All seven phases built. 457 backend tests, including a 64-case object-level
permission matrix, and 48 frontend tests over the logic that has actually broken
here — selection ranges, cover loading states, sort labels.

## Repository

```text
backend/            Django + DRF
  accounts/           users, sessions, password reset, preferences
  library/            folders, books, storage, uploads, reader data, sharing
                      quota.py, retention.py, chunked.py, sorting.py, previews.py
  api/                routing, health probes, OpenAPI schema
  common/             logging with credential redaction, advisory locks
frontend/           Nuxt 3 — library browser, reader, settings
  tests/              Vitest · e2e/  Playwright
caddy/              reverse proxy configuration
deploy/             bootstrap.sh and deploy.sh
docs/               deployment guide and per-phase design records
scripts/            check-contrast.py, e2e.sh
```

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Nuxt 3, Vue 3, TypeScript, PDF.js |
| Backend | Django 5.2 LTS, Django REST Framework |
| Database | PostgreSQL 16 |
| Documents | pypdfium2 (Apache-2.0), Pillow |
| Tests | pytest, Vitest + Vue Test Utils, Playwright, ruff, vue-tsc, ShellCheck |
| Deployment | Docker Compose, Caddy, Ubuntu, Tailscale |

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

- [docs/deployment.md](docs/deployment.md) — deploying (including onto a host
  that already runs something else), backups, restore drills, phones,
  troubleshooting
- [docs/phases/](docs/phases/) — what each phase decided, and the six decisions
  that were expensive to reverse
- [lumaindex-prd.md](lumaindex-prd.md) — the original specification
