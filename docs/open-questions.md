# Gaps, risks, and next actions

Things the PRD leaves undecided or does not mention, found while building
Phase 1. Grouped by when the decision has to be made, because most of these are
cheap now and expensive after data exists.

---

## Already closed in Phase 1

Listed so they do not get re-litigated later.

| Gap | What was done |
| --- | --- |
| PRD requires HttpOnly cookies but never says same-origin. Split origins force CORS + `SameSite=None`, which is the opposite of "restrictive". | Caddy serves Nuxt and Django from one origin; `SameSite=Lax`, no CORS anywhere. |
| Nuxt SSR fetches run on the *server*, which has no browser cookies — every SSR render looks signed-out. | `useApi()` forwards the incoming `Cookie` header during SSR. |
| **Login CSRF.** DRF marks every `APIView` `csrf_exempt` and `SessionAuthentication` only enforces CSRF once a request is authenticated — so anonymous `POST /login` was unprotected. A third-party page could sign a visitor into an attacker's account. Found by testing, not by reading. | `csrf_protect` on login/register/logout/password-change, with regression tests. |
| `SESSION_COOKIE_SECURE=True` silently breaks login over plain HTTP. | `tailscale serve` terminates real TLS; Caddy trusts its `X-Forwarded-Proto`; both flags are env-controlled and documented. |
| PRD §32 says "never log tokens" — a rule with no enforcement. | A logging filter redacts sensitive keys and inline token patterns, with tests. |
| "Encrypted at rest" with no key-management story. | `MultiFernet` with a legacy-key list for rotation, and documented consequences of losing the key. |
| One health endpoint that touches the DB turns a database blip into a restart storm. | Split liveness (no deps, used by Docker) from readiness (DB + cache writability, used by the deploy gate). |
| Non-root containers vs. volume ownership. | Fixed UID 10001, `/data` pre-created and chowned in the image so named volumes inherit it. |
| `Alice@x.com` and `alice@x.com` becoming two accounts — which also makes Google linking ambiguous later. | Email lowercased in the manager and in `save()`. |
| No CI. | GitHub Actions: ruff, `check --deploy`, `makemigrations --check`, pytest, Nuxt build, shellcheck, compose validation. |

---

## Decide before Phase 2 (Google Drive)

### 1. Google OAuth scope and verification — the biggest risk in the project
`drive.readonly` is a **restricted** scope: publishing an app that uses it
requires Google verification plus an annual third-party security assessment
priced for companies. Staying in "Testing" mode avoids that, but **refresh
tokens then expire after 7 days** — Drive sync breaks roughly weekly for every
user.

**Action:** pick a route from [google-oauth.md](google-oauth.md) — Testing mode
(accept weekly reconnects), Workspace-internal (best if available), or
`drive.file` + Picker (no verification, different import UX). Do this before
writing sync code; it changes the model.

### 2. Account linking is an account-takeover path
If Google sign-in auto-links to an existing account by matching email addresses,
anything that yields an unverified email claim becomes a takeover.

**Action:** only auto-link when the ID token's `email_verified` is `true`.
Otherwise require the user to sign in with their password first and link
explicitly. Write the test alongside the code.

### 3. Thumbnail library — check the licence before adopting
PyMuPDF is the obvious choice for rendering a first-page thumbnail and reading
`page_count`, and it is **AGPL**. For a self-hosted app you distribute, that may
or may not be acceptable. `pypdfium2` (Apache/BSD) does the same job.

**Action:** decide deliberately rather than by `pip install`.

### 4. Sync safety rails
Small, cheap, and annoying to retrofit:

- **Concurrency:** two syncs on one connection will duplicate work and race.
  Add a `DriveConnection.sync_status` plus a Postgres advisory lock.
- **`startPageToken`:** store one per connection from day one. It costs nothing
  now and is the only path to incremental sync later without re-listing.
- **Shared drives:** pass `supportsAllDrives` / `includeItemsFromAllDrives`.
- **Shortcuts:** resolve `shortcutDetails.targetId` or import broken records.
- **Backoff:** exponential retry on `userRateLimitExceeded`; use `fields=`
  projections to stay under quota.

### 5. Cache identity
PRD §25 says never trust filenames. Go further: key the cache on
`(provider, file_id, provider_modified_at)` — including the version — so a
changed file invalidates itself instead of serving a stale PDF forever.

---

## Decide before Phase 4 (reader)

### 6. PDF streaming will tie up a worker per download
PDF.js issues HTTP **Range** requests. Two consequences the PRD does not cover:

- The content endpoint **must** support `Range` and return `206`, or PDF.js
  falls back to downloading the whole file before rendering page 1.
- Streaming a 200 MB PDF through gunicorn occupies a sync worker for the entire
  download. Three workers, three big reads, and the instance is wedged.

**Action:** serve cached files via an internal redirect (nginx `X-Accel-Redirect`,
or Caddy's `internal` + a signed path) so Django authorizes and the proxy moves
the bytes. Decide this before the reader ships — it affects the endpoint's shape.

### 7. Highlight anchoring format
PRD §23 says "store positions independently from viewport pixels" without
saying how. Migrating annotation coordinates after users have created them is
the kind of task that gets postponed forever.

**Action:** store page index plus quad points in **PDF user space** (via
`viewport.convertToPdfPoint`), and version the `position_data` schema from the
first write.

### 8. Reading progress has no conflict-resolution rule
PRD §19 and §21 describe per-user progress and cross-device resume, but two
devices open at once is undefined. Last-write-wins will silently rewind a reader
who left a phone open on page 3.

**Action:** pick a rule and write it down. Suggested: last-write-wins keyed on a
client-supplied timestamp, ignoring updates older than the stored `updated_at`.

### 9. Scanned PDFs need a detected flag, not a runtime guess
PRD §27 wants the user told when text search is unavailable.

**Action:** probe for a text layer at import and store `has_text_layer` on the
book, so the UI can say so before the user searches and gets nothing.

---

## Decide before Phase 6 (sharing)

### 10. Deletion semantics are undefined per-relationship
PRD §33 says account deletion "must define what happens" and leaves it there.
Every FK needs an explicit `on_delete`, and the interesting cases are:

- Owner deleted → their `SHARED` books vanish. What happens to **other users'**
  progress, bookmarks, and highlights on those books? Cascade, or orphan and
  retain?
- Book deleted from Drive → PRD §13 says annotations must survive. So the
  annotation FK cannot cascade from `BookSource`.
- User disabled (not deleted) → shared books should stay readable or not?

**Action:** write the matrix into the model layer as explicit `on_delete=`
choices, and test the two-user cases before sharing ships.

### 11. Cache eviction races across workers
"Maximum cache size" with automatic cleanup (PRD §25) means multiple gunicorn
workers deleting from one directory concurrently.

**Action:** one sweeper holding an advisory lock, not per-request eviction.

---

## Operational

### 12. Password reset has no mail path
PRD §7 requires password reset; nothing in the PRD sends email. The instance
ships with the console backend, so reset links land in the backend log.

**Action:** fine for a single user. Before a second person depends on it, point
`LUMA_EMAIL_BACKEND=smtp` at a relay (Fastmail, SES, Resend) — a Tailscale-only
box has no deliverable mail path of its own.

### 13. The PDF cache can take the database down
`pdf-cache` and `postgres-data` share a filesystem. An unbounded cache fills the
disk and Postgres stops accepting writes.

**Action:** enforce `LUMA_PDF_CACHE_MAX_BYTES` in the eviction sweeper (it is
currently declared, not enforced), and alert on free space. `deploy.sh status`
shows disk usage; something should watch it when you are not looking.

### 14. Postgres major version is pinned — keep it that way deliberately
`postgres:16-alpine`. Bumping to 17 will not read a 16 data directory; it needs
a dump/restore or `pg_upgrade`.

**Action:** treat a major bump as a planned migration with a tested restore, not
a tag change.

### 15. Backups are local-only and untested
`deploy.sh backup` writes to the same host it is backing up. That covers "I broke
the database", not "the disk died".

**Action:** copy dumps off-box on a schedule (`--download` from a cron on your
laptop, or a restic/rclone target), and **run a restore drill now** rather than
discovering the gap during an incident. Back up
`LUMA_FIELD_ENCRYPTION_KEY` separately from the dump it decrypts.

### 16. Nothing scheduled runs yet
Periodic Drive sync (PRD §13) and cache cleanup have no runner, and the PRD
correctly says not to add Celery yet.

**Action:** a systemd timer on the host calling
`docker compose exec backend python manage.py <cmd>` covers both until the
workload justifies Celery. Design the commands to be idempotent and safely
re-entrant from the start.

---

## Suggested order

1. Restore drill + off-box backups (**do this before there is data worth losing**)
2. Google OAuth scope decision — it gates all of Phase 2
3. `email_verified` rule for account linking
4. Deletion/`on_delete` matrix — cheap now, painful after users share books
5. PDF streaming approach — settle before the reader endpoint exists
6. Highlight anchoring schema — settle before the first highlight is stored
7. Everything else, as its phase arrives
