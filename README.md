# LumaIndex

A self-hosted, multi-user web application for browsing, organizing, sharing, and reading PDF ebooks.

Users sign in with a normal application account — no Google account required. Users who *do* connect Google Drive can import PDFs recursively from folders they select, while Drive remains the source of truth for those files. Everything else — identity, library metadata, collections, sharing, reading progress, bookmarks, highlights, and notes — lives in Django/PostgreSQL.

Designed to run on an Ubuntu server behind Tailscale, and to be read from desktop, tablet, and mobile browsers.

---

## Status

**Phase 1 — platform foundation — is built and deployable.** Everything from
Phase 2 onward (Google Drive, the library, the reader) is still to come.

Working today: Docker Compose stack, PostgreSQL, Django + DRF with a custom
user model, session-cookie authentication, Django Admin, an OpenAPI schema, a
Nuxt frontend with sign-in, and a one-command SSH deploy to Ubuntu behind
Tailscale.

- [lumaindex-prd.md](lumaindex-prd.md) — the full PRD, and the source of truth
  for scope and behaviour. Where this README and the PRD disagree, the PRD wins.
- [docs/deployment.md](docs/deployment.md) — deploying, backups, troubleshooting.
- [docs/google-oauth.md](docs/google-oauth.md) — **read before Phase 2.** The
  Drive scope decision has consequences that are expensive to reverse.
- [docs/open-questions.md](docs/open-questions.md) — gaps the PRD leaves open,
  with the decision each one needs and when it has to be made.
- [docs/phases/](docs/phases/) — Phases 2–7 scoped: data models, APIs, risks,
  and the decisions to settle before writing each one.

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
2. A Google account is optional; Google Drive is an optional *storage provider*, not an identity requirement.
3. **Books are private by default.**
4. Shared books are readable by any authenticated user on the instance — including users with no Google account.
5. Reading progress, bookmarks, highlights, and notes are **always per-user and private by default**.
6. Application collections never modify the original Google Drive structure.
7. Google Drive stays canonical storage for imported PDFs.
8. **Authorization is always enforced server-side by Django** — never by hiding UI in Nuxt.

---

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Nuxt 3, Vue 3, TypeScript, PDF.js |
| Backend | Django, Django REST Framework, django-allauth |
| Database | PostgreSQL |
| External | Google OAuth, Google Drive API |
| Deployment | Docker Compose, Ubuntu Server, Tailscale |

Celery and Redis are deliberately **not** part of the initial build. They get introduced only when an asynchronous workload actually justifies them (large Drive syncs, thumbnail generation at scale, OCR, AI indexing).

---

## Architecture

```text
                    Google Drive
                         |
                  Google Drive API
                         |
                         v
                 ┌────────────────┐
                 │ Django Backend │
                 │                │
                 │ DRF API        │
                 │ Authentication │
                 │ Authorization  │
                 │ Drive Sync     │
                 │ Book Sharing   │
                 │ PDF Delivery   │
                 └───────┬────────┘
                         |
              ┌──────────┼───────────┐
              v          v           v
         PostgreSQL   PDF Cache   Thumbnails
              ^
              |
          REST API
              |
              v
          ┌────────┐
          │ Nuxt 3 │
          │ PDF.js │
          └────┬───┘
               |
           Tailscale
               |
       Desktop / Tablet / Mobile
```

Every PDF byte a reader receives passes through Django's authorization boundary. Django may fetch and cache a PDF using the *owner's* Drive connection, but the owner's Drive credentials are never exposed to readers, and the cache directory is never served as unrestricted static content.

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
Book ──> BookSource ──> Google Drive
                        (later: local upload, Dropbox, OneDrive)
```

This lets new storage providers be added without redesigning the library or reader domains.

The other structural split is **source organization vs. logical organization**:

- Drive folders describe where a file physically lives, and are preserved on import (file ID, parent ID, original path, filename, MIME type, size, modified timestamp).
- Application collections are independent, user-owned, nestable, and many-to-many with books. The same book can sit in *Currently Reading*, *Software Engineering*, and *Favourites* at once without duplicating the PDF — and moving it between collections never touches Drive.

Principal entities: `User` (custom model, email as login identifier), `DriveConnection`, `DriveRoot`, `Book`, `BookSource`, `Collection`, `CollectionBook`, `ReadingProgress` (unique per `user, book`), `Bookmark`, `Highlight`, `UserSettings`. Field-level detail is in [§28 of the PRD](lumaindex-prd.md).

---

## API surface

REST via DRF, with an OpenAPI schema and browsable docs in development.

```text
/api/auth/          /api/library/       /api/reader/
/api/users/         /api/books/         /api/shared/
/api/drive/         /api/collections/
```

Representative endpoints:

```text
GET    /api/books/                      GET    /api/books/{id}/progress
GET    /api/books/{id}/                 PUT    /api/books/{id}/progress
GET    /api/books/{id}/content          GET    /api/books/{id}/bookmarks
PATCH  /api/books/{id}/                 POST   /api/books/{id}/highlights

GET    /api/collections/                POST   /api/drive/connect/
GET    /api/shared/books/               POST   /api/drive/sync/
```

Object-level permissions apply to API endpoints, PDF streaming, cache access, thumbnails, modifications, and sharing actions alike.

---

## Security model

- HttpOnly, secure, correctly-`SameSite`d session cookies; CSRF protection. Auth tokens are not kept in `localStorage`.
- Google OAuth refresh tokens are **encrypted at rest**, never logged, never returned to other users, and never displayed in plaintext in Django Admin.
- The least-privileged Drive scope that supports recursive folder reading — scope choice must be validated early, since broader scopes trigger additional Google verification requirements.
- `DEBUG=False`, restrictive `ALLOWED_HOSTS`, correct trusted origins, non-root containers, secrets via environment/Docker secrets.
- Sharing a book inside LumaIndex never changes its Google Drive sharing permissions.
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
| [2 — Google Drive](docs/phases/02-google-drive.md) | Account linking, Drive OAuth, connection model, root folder selection, recursive PDF discovery, initial sync, PDF cache, thumbnails |
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

EPUB, MOBI/AZW, DRM, OCR, AI features, semantic/vector search, audiobooks, anonymous or public reading, open public registration, complex sharing ACLs, groups, PDF editing, modifying Drive folders, Dropbox, OneDrive, and native mobile apps.

Several of these — PWA offline reading, OCR, EPUB, tags, ratings, reading statistics, annotation export, AI Q&A and semantic search over pgvector — are listed as plausible future work in [§43 of the PRD](lumaindex-prd.md). The architecture should leave room for them without being built for them now.
