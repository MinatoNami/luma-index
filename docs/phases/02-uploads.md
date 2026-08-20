# Phase 2 — Uploads, folders, and storage

**Goal:** upload PDFs — singly or as a ZIP whose folder structure is rebuilt —
and organise them in folders. LumaIndex owns the files.

**Built:** storage, folders, trash, ZIP import, the ingest worker, the file
browser. 141 tests.

## What changed from the PRD

The PRD assumed Google Drive was canonical storage and LumaIndex kept a
disposable cache (§10, §13, §25, §38). Three consequences its text does not
cover:

| PRD assumption | Now |
| --- | --- |
| Drive folders are the source hierarchy; app collections are a separate logical layer (§11) | One folder tree, owned by the app and edited by the user. Collections remain a many-to-many layer on top. |
| The local copy is a cache, evictable under a size cap (§25) | Canonical storage. Nothing is evicted; an upload is refused when the disk is low. |
| Cache and thumbnails need no backup (§38) | The `library` volume is irreplaceable and is backed up with the database. Thumbnails still are not. |

Deleting became a **trash**, because an uploaded PDF may be the only copy its
owner has. The PRD's §14 `Book`/`BookSource` split survives and still earns its
place: it is what lets a replaced scan change the bytes without touching a
book's annotations.

## Storage

Content-addressed — a file's SHA-256 is its identity and its path
(`library/ab/cd/abcd….pdf`):

- **The same file twice stores one copy,** so retrying a half-dead ZIP import
  costs no extra disk, which is what makes "skip duplicates" a safe default.
- **Two books can share one blob,** so deleting a book removes the file only
  once nothing references it.
- **A changed file is a different key,** so nothing can serve stale bytes.

Writes stage and rename, so an interrupted upload leaves nothing a later read
could mistake for a complete file.

## ZIP import

Archives are hostile input. `zip_import.py` validates before anything is
written, and 27 tests cover the ways it goes wrong:

| Attack | Guard |
| --- | --- |
| Zip slip (`../../etc/cron.d/x`) | Path normalisation; unsafe entries rejected, not sanitised |
| Absolute paths, Windows paths, `C:\` | Same |
| Symlink entries | Rejected via the Unix mode bits in `external_attr` |
| Zip bomb | Compression-ratio cap, per-entry cap, total-expansion cap |
| Header lying about a size | The write is bounded and aborts when it overruns |
| Non-PDF with a `.pdf` name | `%PDF-` magic checked at extraction |
| Deeply nested paths | Depth cap |
| `__MACOSX/`, `.DS_Store`, `._x` | Ignored, and not counted as skipped |

Extraction runs in the worker: a few hundred books take minutes and a request
would time out, so the endpoint stages the archive and returns an `UploadBatch`
the UI polls.

## Folders

Invariants live in the model, not the view: no cycles, no moving a folder into
its own subtree, a depth cap, no reparenting under another user's folder, and
unique names per parent. That last needs **two** partial constraints, because
PostgreSQL treats NULL parents as distinct and a single
`UNIQUE(owner, parent, name)` would allow two "Books" at the top level.
Uniqueness applies only to live folders, so a trashed name can be reused.

Trashing a folder trashes its subtree and books. Restoring brings back what was
trashed *with it*, and deliberately not something deleted separately beforehand.

## Left open at the time, since built

Per-user quotas (`library/quota.py`), move-to-a-chosen-folder, automatic trash
expiry (`library/retention.py`), and resumable chunked uploads
(`library/chunked.py`). Still unbuilt: replacing a book's file while keeping its
annotations — the model supports it, no endpoint exposes it.
