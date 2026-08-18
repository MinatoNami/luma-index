# Phase 2 — Google Drive

**Goal:** a user connects their Drive, picks folders, and their PDFs appear as
books with thumbnails. PDFs are served from a server-side cache through
Django's authorization boundary — never straight from Drive to the browser.

**Unblocks:** everything. Phases 3–6 all assume `Book` and `BookSource` exist.

**Status:** backend complete — models, Drive client, OAuth, sync, worker, cache,
and thumbnails, with 155 tests. Built for the API-driven folder browse, which is
identical under OAuth routes 1 and 2; route 3 (`drive.file` + Picker) would
change only the folder-selection UI. Not yet exercised against real Google
credentials — D1 is still open.

---

## Decide before writing code

### D1. OAuth scope route — **blocking**
See [google-oauth.md](../google-oauth.md). Testing mode, Workspace-internal, or
`drive.file` + Picker. The choice changes the import UX and whether refresh
tokens survive more than 7 days, so it cannot be deferred past the OAuth code.

### D2. PDF rendering library
Needed for thumbnails, `page_count`, and text-layer detection.

| Option | Licence | Notes |
| --- | --- | --- |
| **pypdfium2** (recommended) | Apache-2.0 / BSD | Chromium's PDFium. Fast, permissive, wheels for arm64 and amd64. |
| PyMuPDF | **AGPL-3.0** | Excellent, but AGPL applies to a self-hosted app you distribute. |
| pdf2image + poppler | GPL binary, subprocess | Extra system dependency, slowest. |

Recommendation: **pypdfium2**. Decide deliberately; retrofitting a licence
change after it is woven through import and search is far more work.

### D3. Where sync runs — **the significant architectural call**
Sync walks folders, downloads PDFs, and renders thumbnails. That cannot happen
inside a request: a large first sync takes minutes and would hit gunicorn's
timeout. PRD §36 forbids Celery for now and permits "lightweight application
mechanisms".

Recommendation: a fourth compose service running a **polling worker**:

```
worker:  python manage.py run_sync_worker
```

A loop that wakes every ~15s, claims due or user-requested syncs with a
PostgreSQL advisory lock, and runs them. No Redis, no broker, no new
dependency — a management command and a `while True`. It gives near-immediate
"Sync now", survives restarts, and cannot double-run a connection.

Rejected: threads inside gunicorn (a worker restart kills a sync mid-flight);
a systemd timer on the host (couples the app to host configuration and makes
"Sync now" wait for the next tick).

When the workload outgrows this, the same management command becomes a Celery
task with no change to the domain code — which is what §36 asks for.

### D4. Cache identity
Key cached files on `(provider, provider_file_id, provider_modified_at)`.
Including the version means a changed file invalidates itself instead of
serving a stale PDF forever. PRD §25 says never trust filenames; a file ID
alone is not enough either.

---

## Data model

```text
DriveConnection            one per user per Google account
  user                     FK -> User, on_delete=CASCADE
  provider_account_id      Google 'sub' claim, unique per user
  encrypted_refresh_token  EncryptedTextField (already built)
  scopes_granted           what the user actually consented to
  status                   active | expired | revoked | error
  status_detail            operator-facing reason, never a token
  start_page_token         for incremental sync later — store from day one
  last_synced_at
  sync_requested_at        set by "Sync now", cleared by the worker

DriveRoot                  a folder the user chose to import
  drive_connection         FK, on_delete=CASCADE
  provider_folder_id
  name, original_path
  sync_enabled
  last_synced_at

Book                       the logical book (PRD §14)
  owner                    FK -> User, on_delete=CASCADE
  title                    defaults to the filename, editable later
  page_count               null until probed
  has_text_layer           null = unknown; drives PRD §27 messaging
  visibility               PRIVATE | SHARED, default PRIVATE
  thumbnail_path
  created_at, updated_at

BookSource                 where the bytes live
  book                     FK, on_delete=CASCADE
  drive_connection         FK, on_delete=SET_NULL, null=True
  provider                 'google_drive'
  provider_file_id         unique with provider
  provider_parent_id, original_path, filename
  mime_type, file_size, provider_modified_at, provider_checksum
  availability_status      available | missing | forbidden | error
  last_seen_at
  created_at, updated_at

SyncRun                    PRD §8 "inspect sync failures" needs a record
  drive_connection         FK, on_delete=CASCADE
  started_at, finished_at
  status                   running | ok | partial | failed
  counts                   JSON: discovered/added/updated/removed/failed
  error_summary            redacted
```

`unique_together` on `(provider, provider_file_id)` and on
`(drive_connection, provider_folder_id)`.

**`on_delete` note:** `BookSource.drive_connection` is `SET_NULL`, not
`CASCADE`. Disconnecting Drive must not delete the library — PRD §33 is
explicit that annotations survive a disconnect, and cascading here would take
the books out from under them.

---

## API

```text
GET    /api/drive/status/            connection state, last sync, counts
POST   /api/drive/connect/           -> {authorization_url, state}
GET    /api/drive/oauth/callback     exchanges the code, stores the token
POST   /api/drive/disconnect/        {delete_library: bool}

GET    /api/drive/folders/?parent=   browse Drive folders for the picker
GET    /api/drive/roots/             selected roots
POST   /api/drive/roots/             add a root
DELETE /api/drive/roots/{id}/        {keep_books: bool}

POST   /api/drive/sync/              request a sync; 202 + SyncRun id
GET    /api/drive/sync/{id}/         progress and result
GET    /api/drive/sync/              recent runs
```

OAuth `state` must be a signed, single-use, session-bound value. A `state`
that is not checked is how an attacker attaches *their* Drive to *your*
account.

---

## Backend work

1. `integrations/google_drive/` app: client wrapper, OAuth flow, sync service.
2. Token refresh with `invalid_grant` handling → set `status=expired` and
   surface "Reconnect Drive". Never delete books or annotations on this path.
3. Recursive listing with `q="'<id>' in parents and trashed=false"`,
   `fields=` projections, pagination, and exponential backoff on
   `userRateLimitExceeded`.
4. Pass `supportsAllDrives=true` and `includeItemsFromAllDrives=true`, or files
   in Shared Drives are invisible.
5. Resolve `application/vnd.google-apps.shortcut` via
   `shortcutDetails.targetId`; skip Google-native types.
6. Upsert by file ID — never by name or path, so renames and moves update
   rather than duplicate (PRD §13).
7. Files that disappear become `availability_status=missing`. **Never delete a
   Book because a Drive listing came back short**; an API error must not look
   like a deletion.
8. Cache fetch-on-demand with an LRU sweeper enforcing
   `LUMA_PDF_CACHE_MAX_BYTES`, holding an advisory lock so workers do not race.
9. Thumbnail + `page_count` + `has_text_layer` at import.
10. `run_sync_worker` management command (D3).
11. Register everything in Django Admin, with the encrypted token **never**
    rendered (PRD §34).

## Frontend work

- Settings → "Connect Google Drive", status, last sync, reconnect prompt.
- Folder picker (or Google Picker under D3/`drive.file`).
- Sync progress, and a clear message when a connection has expired.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Testing-mode refresh tokens expire after 7 days | Model `status=expired` from day one and make reconnect a first-class UI state, not an error page. |
| A big first sync looks broken | `SyncRun` progress counts, surfaced live. |
| Drive quota exhaustion on large libraries | Field projections, pagination, backoff, and per-connection concurrency of one. |
| Cache fills the disk and stops Postgres | Enforce the byte cap in the sweeper; alert on free space. |
| Partial sync leaves the library half-updated | Per-file commits and `status=partial` rather than one giant transaction. |

## Acceptance (PRD §45)

Criteria **6, 7, 8, 9** directly; **25** (revocation handled safely) and **26**
(unavailable files do not destroy metadata) are proven here and re-tested in
Phase 7.

Add: reconnecting after a revoked token restores sync without any book,
progress, bookmark, or highlight loss.

**Rough size:** the largest phase. OAuth + sync + cache + thumbnails are four
distinct pieces; expect the sync edge cases to outweigh the happy path.
