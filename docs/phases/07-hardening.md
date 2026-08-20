# Phase 7 — Hardening

**Goal:** prove the things the earlier phases claim. Every item is a test or a
drill, not a feature.

**Depends on:** everything.

## The permission matrix

§29 requires server-side authorization on API endpoints, PDF streaming,
thumbnails, modifications and sharing actions. Phase 6 put that behind one
function; this phase proves it holds on every path. It is a parametrised test —
`library/tests/test_permission_matrix.py` — of three users against a private and
a shared book, built as a matrix so a gap shows up as a missing row rather than
an absent file.

| Path | owner/private | other/private | other/shared | admin/private |
| --- | --- | --- | --- | --- |
| `GET /books/{id}/` | 200 | 404 | 200 | **404** |
| `GET /books/{id}/content` | 200 | 404 | 200 | **404** |
| `GET /books/{id}/thumbnail` | 200 | 404 | 200 | **404** |
| `PATCH /books/{id}/` | 200 | 404 | 403 | **404** |
| `GET /books/{id}/progress` | own | own | own | own |
| `GET /books/{id}/highlights` | own only | own only | own only | **own only** |
| `POST /books/{id}/bookmarks` | 201 | 404 | 201 | **404** |

Two deliberate choices in that table:

- **404, not 403, for a private book.** A 403 confirms the book exists, which is
  itself a disclosure.
- **Admin gets nothing extra.** §8: admin status must not automatically expose
  private annotations through the normal UI. Instance management happens in
  Django Admin, a separate and audited path.

## What is enforced

- CSRF on every unsafe method **including anonymous ones** — DRF exempts
  APIViews by default, which leaves login open to CSRF. This was a real bug once.
- Authentication rate-limited per address *and* per targeted account, so
  credential stuffing against one user is capped even if address attribution is
  wrong. `LUMA_NUM_PROXIES` decides which `X-Forwarded-For` hop is trusted:
  too high and a client forges its own identity, too low and everyone shares one
  bucket. Verify it on the server with `LUMA_LOG_CLIENT_IP=True`, not in tests.
- Credentials redacted from logs by a filter rather than by convention.
- Uploads sniffed for `%PDF-` rather than trusted by extension; archives
  validated entry by entry before anything is written.
- Containers run non-root, and the entrypoint refuses to start when a storage
  volume is not writable rather than failing later on the first upload.

CI runs ruff, `manage.py check --deploy --fail-level ERROR`, a
`makemigrations --check`, the backend suite, `vue-tsc`, the frontend suite, a
production build, ShellCheck over the deploy scripts, and compose validation.
Dependency auditing (`pip-audit`, `npm audit`) is not wired in.

## What this phase dropped

Two sections of the original plan are moot. **OAuth and Drive failure handling**
— revoked refresh tokens, Drive 5xx, quota exhaustion, files renamed or deleted
upstream — went with Drive itself. So did **cache and disk**: there is no
evictable PDF cache to enforce a size cap on or to evict under a lock, because
storage is canonical now. What replaced them is the free-disk floor, per-account
quotas, and the backup and restore work in
[deployment.md](../deployment.md#backups).

What survived from both: a corrupt PDF fails that file only and the import
continues, a password-protected PDF is detected and flagged rather than raising
a 500, and a missing file marks the source unavailable while leaving the book
and every annotation intact.

## What is still a hypothesis

The permission matrix, the annotation and sharing suites, the range and
conditional-request tests, and the storage and archive guards all run in CI. The
restore *drill* runs against the real server. What has not been done is a
restore onto an empty host, timed end to end — plus the other items in the
README's [known gaps](../../README.md#known-gaps). "How long to recover?" still
needs a number rather than a shrug.
