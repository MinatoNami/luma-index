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
| **Upload** | Drop in PDFs, or a ZIP whose folder structure is rebuilt on import. Identical files are stored once. |
| **Organise** | Folders you create, rename, move, and delete. Deleting goes to a trash you can restore from. |
| **Read** | A PDF.js reader: continuous scroll or single page, zoom, text selection, search within the book, an outline sidebar, page thumbnails. |
| **Resume** | Your place is saved as you read and picked up on any other device. |
| **Annotate** | Bookmarks, highlighted passages in four colours, notes on a highlight, and page notes for scans with no text layer. |
| **Share** | Mark a book shared and anyone signed in can read it — while keeping their own place and their own notes. |

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

| What | Detail |
| --- | --- |
| **Removing and recolouring highlights** | Creating them is confirmed working in a real browser. The remove/recolour/note controls were added afterwards and have not been exercised there. |
| **Single-page mode painting** | Navigation is fixed and verified as far as the tooling allows — the page element is replaced correctly and the counter tracks it. Whether the new page paints needs a real browser. |
| **The reader on a tablet** | PRD §39 calls tablet a primary reading target. Touch selection and memory behaviour have only been checked on a desktop browser. |

The first two share a cause: the development preview pane cannot render PDFs at
all. PDF.js drives its render loop with `requestAnimationFrame`, and that pane
runs with `document.visibilityState: 'hidden'`, where rAF never fires — so a
render never completes and nothing downstream of it runs. **Anything needing
pixels on a page has to be checked in a real browser.**

### Missing for now

| What | Consequence |
| --- | --- |
| **Per-user storage quotas** | A global maximum upload size and a free-disk floor exist, but nothing stops one account filling the disk. |
| **Moving to an arbitrary folder** | The row menu offers "move up one level" only — no folder picker, no drag-onto-folder. The main place this feels less capable than Drive. |
| **Real email delivery** | Password reset works, but the console backend prints reset links into the log. Point `LUMA_EMAIL_BACKEND` at an SMTP relay before a second person has an account. |
| **Off-box backups** | `deploy.sh backup` writes to the host it is backing up. The restore procedure itself has been rehearsed — see [the drill](docs/deployment.md#the-restore-drill) — but copying dumps and the `library` volume elsewhere is still manual. |
| **Emptying the trash automatically** | Trashed items stay until deleted by hand. |
| **Collections and favourites** | Phase 3's remaining half. Search, sort, and the three library views exist; the many-to-many layer does not. |
| **Sharing with named people or groups** | §16 keeps this to private or shared-with-everyone-signed-in. The richer model is §43 future work and would change `library/permissions.py` alone. |

### Open question

**Whether large reads should bypass gunicorn.** Byte ranges work, so a big book
opens quickly, but a long download still occupies a worker for its duration. A
tuning question now rather than a design one.

---

## Status

| Phase | State |
| --- | --- |
| 1 — Platform, auth, deployment | Built |
| 2 — Uploads, folders, storage | Built |
| 3 — Library | Views, search and sort built; collections and favourites not |
| 4 — PDF reader | Built |
| 5 — Bookmarks, highlights, notes | Built |
| 6 — Sharing | Built |
| 7 — Hardening | Built |

307 backend tests, including a 64-case object-level permission matrix.

---

## Repository

```text
backend/            Django + DRF
  accounts/           users, sessions, password reset, preferences
  library/            folders, books, storage, uploads, reader data, sharing
  api/                routing, health probes, OpenAPI schema
  common/             logging with credential redaction, advisory locks
frontend/           Nuxt 3 — library browser, reader, settings
caddy/              reverse proxy configuration
deploy/             bootstrap.sh and deploy.sh
docs/               deployment guide and per-phase design records
scripts/            check-contrast.py — verifies the palette against WCAG AA
```

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Nuxt 3, Vue 3, TypeScript, PDF.js |
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
