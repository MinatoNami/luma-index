# LumaIndex

A self-hosted, multi-user web application for browsing, organizing, sharing, and reading PDF ebooks.

Users sign in with a normal application account, upload their PDFs — one at a time, or as a ZIP whose folder structure is rebuilt on import — and organise them in folders they can create, rename, move, and delete. LumaIndex owns the files; everything else lives in Django/PostgreSQL.

> **Note:** the PRD in this repository specifies Google Drive as canonical storage. That was built and then removed in favour of uploads. Where the PRD and this README disagree about storage, this README is current; the PRD remains the reference for the reader, sharing, and annotation phases still to come.

Designed to run on an Ubuntu server behind Tailscale, and to be read from desktop, tablet, and mobile browsers.

---

## Status

**Phases 1, 2 and 4 are built**, Phase 3 in part, and Phase 5's backend.
Sharing and hardening are still to come. See [Known gaps](#known-gaps) for what
is unproven.

Working today: Docker Compose stack, PostgreSQL, Django + DRF with a custom
user model, session-cookie authentication with password reset, Django Admin, an
OpenAPI schema, PDF and ZIP upload with folder-structure import, a folder tree
with rename/move/trash, content-addressed storage, an ingest worker that probes
page counts and renders thumbnails, a Nuxt file browser, and a one-command SSH
deploy to Ubuntu behind Tailscale.

Working today also: a PDF.js reader with continuous and single-page modes,
zoom, text selection, in-book search, page thumbnails, an outline sidebar, and
reading position synced across devices. Bookmarks, highlights and notes have a
tested API; their interface is written but unverified.

Not built yet: sharing between users, and Phase 3's collections and favourites.

- [lumaindex-prd.md](lumaindex-prd.md) — the full PRD, and the source of truth
  for scope and behaviour. Where this README and the PRD disagree, the PRD wins.
- [docs/deployment.md](docs/deployment.md) — deploying, backups, troubleshooting.
- [docs/open-questions.md](docs/open-questions.md) — gaps the PRD leaves open,
  with the decision each one needs and when it has to be made.
- [docs/phases/](docs/phases/) — Phases 2–7 scoped: data models, APIs, risks,
  and the decisions to settle before writing each one.

---

## Known gaps

Things that are built but unproven, or deliberately missing. Kept here so none
of it has to be rediscovered.

### Unverified

| What | Why it is unverified |
| --- | --- |
| **The annotation UI** — selection toolbar, highlight overlay, notes panel | Written and building, never exercised in a browser. PDF.js drives its render loop with `requestAnimationFrame`, and the development preview pane runs with `document.visibilityState: 'hidden'`, where rAF never fires — so a render never completes and nothing downstream of it runs. The backend behind it is covered by tests. **Open a book in a real browser and highlight a passage; if nothing paints, look at `paintHighlights` and the `props.highlights` watcher.** |
| **The reader on a tablet** | PRD §39 calls tablet a primary reading target. Touch selection and memory behaviour have only been checked on a desktop browser. |

### Missing on purpose, for now

| What | Consequence |
| --- | --- |
| **Per-user storage quotas** | There is a global maximum upload size and a free-disk floor, but nothing stops one account filling the disk. Fine for a household; needed before strangers share an instance. |
| **Moving items to an arbitrary folder** | The row menu offers "move up one level" only. No folder picker and no drag-onto-folder, which is the main place this still feels less capable than Drive. |
| **Real email delivery** | Password reset works, but the console backend prints reset links into the backend log. Anyone who can read logs can take over any account, so point `LUMA_EMAIL_BACKEND` at an SMTP relay before a second person has an account. |
| **Off-box backups, and a restore drill** | `deploy.sh backup` writes to the same host it is backing up. That covers "I broke the database", not "the disk died". A restore has never been rehearsed. |
| **Emptying the trash automatically** | Trashed items stay until deleted by hand. |
| **Collections and favourites** | Phase 3's remaining half. Search, sort, and the three views exist; the many-to-many layer does not. |

### Decisions still open

Both get harder the longer they wait, and both are argued in
[docs/phases/](docs/phases/):

- **The deletion matrix** (Phase 6) — what happens to *other people's*
  annotations when an owner deletes their account or un-shares a book. PRD §33
  leaves it undefined.
- **Whether large reads should bypass gunicorn** — byte ranges work, so a big
  book opens quickly, but a long download still occupies a worker.

---

## Quick start

Local:

```bash
cp .env.example .env && docker compose -f compose.yaml -f compose.dev.yaml up --build
```

To the server:

```bash
cp deploy/deploy.env.example deploy/deploy.env   # where to deploy
```

```bash
./deploy/deploy.sh bootstrap                      # one-time server prep
```

```bash
cp .env.example .env && $EDITOR .env              # fill in every CHANGE_ME
```

```bash
./deploy/deploy.sh env:push && ./deploy/deploy.sh
```

Full walkthrough in [docs/deployment.md](docs/deployment.md).

---

## Core principles

1. The **Django user is the canonical application identity**. Google is not.
2. **Books are private by default.**
3. Shared books are readable by any authenticated user on the instance.
4. Reading progress, bookmarks, highlights, and notes are **always per-user and private by default**.
5. Uploaded files are **canonical and irreplaceable** — nothing is ever evicted to reclaim space, and deletion is reversible until it is explicitly made permanent.
6. Uploaded archives are **hostile input** until proven otherwise.
7. **Authorization is always enforced server-side by Django** — never by hiding UI in Nuxt.

---

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Nuxt 3, Vue 3, TypeScript, PDF.js |
| Backend | Django, Django REST Framework |
| Database | PostgreSQL |
| Documents | pypdfium2 (probing, thumbnails), Pillow |
| Deployment | Docker Compose, Ubuntu Server, Tailscale |

Celery and Redis are deliberately **not** part of the initial build. They get introduced only when an asynchronous workload actually justifies them (large Drive syncs, thumbnail generation at scale, OCR, AI indexing).

---

## Architecture

```text
       Desktop / Tablet / Mobile
                 |
             Tailscale
                 |
          ┌──────┴──────┐
          │    Caddy    │   one origin: /api → Django, everything else → Nuxt
          └──┬───────┬──┘
             │       │
        ┌────┴───┐ ┌─┴──────────────┐
        │ Nuxt 3 │ │ Django + DRF   │
        │ PDF.js │ │ auth, authz,   │
        └────────┘ │ uploads, ZIP   │
                   │ import, PDF    │
                   │ delivery       │
                   └──┬──────────┬──┘
                      │          │
              ┌───────┴──┐   ┌───┴──────────────┐
              │PostgreSQL│   │ library/  (PDFs) │  canonical — back this up
              └──────────┘   │ thumbnails/      │  regenerable
                      ▲      │ staging/         │  scratch
                      │      └──────────────────┘
              ┌───────┴────────┐
              │ ingest worker  │  extracts ZIPs, probes PDFs, renders covers
              └────────────────┘
```

Every PDF byte a reader receives passes through Django's authorization boundary, and the storage directory is never served as static content.

---

## Repository layout

Built (✅) and planned (·):

```text
backend/
├── config/                  ✅ Django settings, URLs, WSGI/ASGI
├── common/                  ✅ structured logging + credential redaction,
│                               encrypted model fields
├── accounts/                ✅ custom user, session auth, admin
├── api/                     ✅ DRF routing, health probes, OpenAPI
├── integrations/
│   └── google_drive/        ·  OAuth, connections, folder selection, sync
├── library/                 ·  books, book sources, collections, metadata
├── reader/                  ·  progress, bookmarks, highlights, notes, prefs
└── sharing/                 ·  visibility, shared library, access rules

frontend/                    ✅ Nuxt 3 — auth, CSRF, SSR cookie forwarding
caddy/                       ✅ reverse proxy (single origin for app + API)
deploy/                      ✅ bootstrap.sh, deploy.sh
docs/                        ✅ deployment, Google OAuth
```

Django apps should stay loosely coupled.

---

## Domain model

The key design decision is separating a **logical book** from its **storage source**:

```text
Book ──> BookSource ──> local storage
                        (later: a replaced file, or another provider)
```

This lets the bytes behind a book change — a better scan, a different provider — without touching its annotations.

Storage is **content-addressed**: a file's SHA-256 is both its identity and its path. Uploading the same PDF twice stores one copy, so retrying a half-finished ZIP import costs no extra disk; a blob is deleted only once no book references it.

Folders are a plain tree, owned by the user, with the invariants enforced in the model: no cycles, a depth cap, and unique names per parent.

Deletion is a **trash**. An uploaded PDF may be the only copy its owner has, so deleting is reversible and permanent deletion is a separate, explicit step.

Principal entities: `User` (custom model, email as login identifier), `Folder`, `Book`, `BookSource`, `UploadBatch`. Still to come: `ReadingProgress`, `Bookmark`, `Highlight`, `UserSettings`.

---

## API surface

REST via DRF, with an OpenAPI schema and browsable docs in development.

```text
GET    /api/library/folders/            POST   /api/library/upload/
POST   /api/library/folders/            GET    /api/library/uploads/
PATCH  /api/library/folders/{id}/       GET    /api/library/uploads/{id}/
DELETE /api/library/folders/{id}/       GET    /api/library/trash/
POST   /api/library/folders/{id}/restore/
                                        GET    /api/library/storage/
GET    /api/library/books/
PATCH  /api/library/books/{id}/         GET    /api/library/books/{id}/content
DELETE /api/library/books/{id}/         GET    /api/library/books/{id}/thumbnail
POST   /api/library/books/{id}/restore/
```

`?permanent=true` on a delete empties it from the trash for good; without it, the item is recoverable.

Object-level permissions apply to API endpoints, PDF streaming, cache access, thumbnails, modifications, and sharing actions alike.

---

## Security model

- HttpOnly, secure, correctly-`SameSite`d session cookies; CSRF protection. Auth tokens are not kept in `localStorage`.
- Uploaded archives are treated as hostile: zip-slip paths, symlink entries, compression bombs, and entries lying about their size are all rejected before anything is written.
- Uploads are sniffed for `%PDF-` rather than trusted by extension or content type.
- Authentication is rate-limited per address **and** per targeted account.
- `DEBUG=False`, restrictive `ALLOWED_HOSTS`, correct trusted origins, non-root containers, secrets via environment/Docker secrets.
- Failure modes (revoked OAuth, deleted or moved Drive files, Drive API outages, corrupt or encrypted PDFs) must never silently destroy a user's reading state or annotations. Unavailable sources get marked, not deleted.

---

## Deployment

Docker Compose on Ubuntu, initially three services — `frontend`, `backend`, `postgres` — with persistent volumes for `postgres-data`, `pdf-cache`, and `thumbnails`. Access is expected to go through Tailscale; no public internet exposure is required beyond outbound access for Google APIs and OAuth.

`compose.yaml`, `.env.example`, migrations, health checks, restart policies,
and the setup/upgrade/backup procedures all ship in this repo — see
[docs/deployment.md](docs/deployment.md).

Nothing is published past `127.0.0.1`: `tailscale serve` terminates TLS for the
MagicDNS name and forwards to Caddy on loopback, so the app has a real
certificate (and therefore working `Secure` cookies) without exposing a port to
the LAN or the internet.

**Backups:** PostgreSQL holds the irreplaceable data (users, library metadata, collections, sharing, progress, bookmarks, highlights, notes, settings). The PDF cache and thumbnails are regenerable and do not need routine backup.

---

## Roadmap

| Phase | Scope |
| --- | --- |
| 1 — Platform foundation ✅ | Docker Compose, PostgreSQL, Django + DRF, custom User model, Nuxt, authentication, Django Admin, Tailscale deployment |
| [2 — Uploads & folders](docs/phases/02-uploads.md) ✅ | PDF and ZIP upload, content-addressed storage, folder tree with rename/move/trash, ingest worker, thumbnails |
| [3 — Library](docs/phases/03-library.md) | Grid/list views, imported Drive hierarchy, search, sort, filters, nested collections, Favourites, Continue Reading, Unsorted |
| [4 — PDF reader](docs/phases/04-reader.md) | PDF.js, navigation, continuous/single-page modes, zoom, in-document search, table of contents, page thumbnails, preferences, progress sync |
| [5 — Reading data](docs/phases/05-reading-data.md) | Bookmarks, highlights, notes |
| [6 — Sharing](docs/phases/06-sharing.md) | Private/shared visibility, Shared Library, non-Google reader access, authorized PDF streaming, per-user state on shared books |
| [7 — Hardening](docs/phases/07-hardening.md) | Security review, object-level permission tests, OAuth failure handling, resync/recovery, cache limits, large-PDF testing, backup/restore testing, mobile and tablet UX |

Each phase is scoped in [docs/phases/](docs/phases/), including the six
decisions that outlive their phase and should be settled early.

The MVP is judged against the 31 success criteria in [§45 of the PRD](lumaindex-prd.md).

---

## Non-goals for the MVP

EPUB, MOBI/AZW, DRM, OCR, AI features, semantic/vector search, audiobooks, anonymous or public reading, open public registration, complex sharing ACLs, groups, PDF editing, and native mobile apps.

Several of these — PWA offline reading, OCR, EPUB, tags, ratings, reading statistics, annotation export, AI Q&A and semantic search over pgvector — are listed as plausible future work in [§43 of the PRD](lumaindex-prd.md). The architecture should leave room for them without being built for them now.
