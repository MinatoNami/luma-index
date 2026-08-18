# Phase 7 — Hardening

**Goal:** prove the things the earlier phases claim. Every item here is a test
or a drill, not a feature.

**Depends on:** everything.

---

## The permission matrix

PRD §29 requires server-side authorization on API endpoints, PDF streaming,
cache access, thumbnails, modifications, and sharing actions. Phase 6 puts that
behind one function; this phase proves it holds on every path.

Build the matrix as a parametrised test: three users — **owner**, **other**
(no Google account), **admin** — against a private book and a shared book,
across every endpoint.

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

- **404, not 403, for a private book.** A 403 confirms the book exists.
- **Admin gets nothing extra.** PRD §8: "Admin status should not automatically
  expose private user annotations through the normal application UI." Admins
  manage the instance through Django Admin, which is a separate, audited path.

---

## Security review

- [ ] Run the permission matrix above; every cell asserted.
- [ ] `manage.py check --deploy` clean; `DEBUG=False` confirmed on the server.
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` restrictive and correct.
- [ ] Session cookie `HttpOnly` + `Secure`; CSRF enforced on every unsafe
      method **including anonymous ones** — this was a real bug once already.
- [ ] Rate limiting verified *on the server*, not just in tests: confirm
      `LUMA_NUM_PROXIES` yields the real client address in the logs.
- [ ] No secret in any log: grep a full day of output for token prefixes
      (`1//`, `ya29.`), password values, and the encryption key.
- [ ] OAuth `state` is signed, single-use, and session-bound.
- [ ] Refresh tokens never appear in an API response, a template, Django Admin,
      or an error page.
- [ ] Cached PDF paths are unguessable and never served as static content.
- [ ] Uploaded/fetched PDFs cannot escape the cache directory via a crafted
      file ID or path (`..`, absolute paths, null bytes).
- [ ] Dependencies updated; `pip-audit` and `npm audit` clean or triaged.
- [ ] Containers run non-root; volume ownership correct.

## OAuth and Drive failure handling

Each of these gets a test with a **mocked Drive API**, because you cannot
reliably produce them on demand:

- [ ] Refresh token revoked (`invalid_grant`) → status `expired`, reconnect
      prompt, **zero** data loss.
- [ ] Drive API 5xx or timeout → sync marked failed, retried, nothing deleted.
- [ ] Quota exceeded → backoff, partial sync recorded honestly.
- [ ] File deleted in Drive → source `missing`, book and annotations intact.
- [ ] File renamed or moved → same `Book` row updated, not a duplicate.
- [ ] Permission removed on a file → `forbidden`, clear user-facing message.
- [ ] Corrupt PDF → import fails for that file only, sync continues.
- [ ] Password-protected PDF → detected, flagged, not a 500.
- [ ] **Reconnect after revocation restores sync with no data loss.** This is
      criterion 25 and the one most likely to be broken by an innocuous change.

## Large-PDF and device testing

Test with real books, not generated fixtures — page complexity is what hurts.

- [ ] 300 MB+ scanned book opens to page 1 in seconds (proves `Range` works).
- [ ] Scroll 200 pages: browser memory returns to baseline (proves canvas
      eviction works).
- [ ] Three concurrent large downloads: the app stays responsive and the health
      check still answers (proves the Phase 4 D1 decision was implemented).
- [ ] iPad and a mid-range Android phone, on the tailnet, not just a desktop
      window resized narrow.
- [ ] Keyboard-only navigation of library and reader.
- [ ] Screen reader passes the library grid and reader controls.

## Cache and disk

- [ ] `LUMA_PDF_CACHE_MAX_BYTES` is **enforced**, not merely configured.
- [ ] LRU eviction never deletes a file mid-stream.
- [ ] Concurrent eviction across workers holds the advisory lock.
- [ ] Stale entries invalidate when `provider_modified_at` changes.
- [ ] Filling the cache does not stop Postgres accepting writes.
- [ ] Free-space alerting exists somewhere you will actually see it.

## Backup and restore drill

Not "backups configured" — an actual rehearsal:

1. [ ] `./deploy/deploy.sh backup --download`
2. [ ] Restore onto a **scratch host**, not production.
3. [ ] Verify users, library, collections, progress, bookmarks, highlights.
4. [ ] Verify Drive connections decrypt — this is what proves
       `LUMA_FIELD_ENCRYPTION_KEY` was stored somewhere you can still reach.
5. [ ] Time it. "How long to recover?" needs a number, not a shrug.
6. [ ] Confirm dumps land **off the server** on a schedule.
7. [ ] Confirm the encryption key is backed up **separately** from the dump.

## Operations

- [ ] Django Admin covers users, books, sources, connections, roots,
      collections, sync status, shared books (§34), with tokens never in
      plaintext.
- [ ] Health endpoints reflect real dependency state.
- [ ] Log volume is sane; rotation configured (it is, in `daemon.json`).
- [ ] `SyncRun` history is inspectable in Admin (§8).
- [ ] Postgres major-version upgrade path written down and rehearsed once.
- [ ] A documented runbook for: Drive disconnected, disk full, database down,
      bad deploy.

---

## Acceptance (PRD §45)

This phase is where the remaining criteria are proven rather than implemented:
**21** (Django authorizes every content request), **23–24** (no cross-user
access to books or annotations), **25** (revocation handled safely), **26**
(unavailable files preserve metadata), **27** (cache cannot bypass
authorization), **28** (large PDFs usable), **29** (backups restore), **30**
(Admin is operationally sufficient), **31** (OpenAPI schema published).

The MVP is done when all 31 hold — and when the restore drill has been
performed at least once on a host that is not the one being backed up.

**Rough size:** smaller than it looks if the earlier phases were built with
these tests in mind, and much larger if they were not.
