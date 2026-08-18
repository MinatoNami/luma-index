# Phase 2 — Uploads, folders, and storage

**Goal:** users upload PDFs — singly or as a ZIP whose folder structure is
rebuilt — and organise them in folders they can create, rename, move, and
delete. LumaIndex owns the files.

**Status: built.** Storage, folders, trash, ZIP import, the ingest worker, and
the file browser. 141 tests.

---

## What changed from the PRD

The PRD assumed Google Drive was canonical storage and LumaIndex kept a
disposable cache (§10, §13, §25, §38). That is no longer true, and three
consequences follow that the PRD's text does not cover:

| PRD assumption | Now |
| --- | --- |
| Drive folders are the source hierarchy; app collections are a separate logical layer (§11) | One folder tree, owned by the app and edited by the user. Collections remain available later as a many-to-many layer for Favourites and Continue Reading. |
| The local copy is a cache that may be evicted under a size cap (§25) | Canonical storage. Nothing is evicted; an upload is refused when the disk is low. |
| Cache and thumbnails need no backup (§38) | The `library` volume is irreplaceable and must be backed up with the database. Thumbnails still do not. |

Deleting is now a **trash**: an uploaded PDF may be the only copy its owner
has, so a stray click has to be reversible.

The PRD's §14 `Book`/`BookSource` split survives, and still earns its place —
it is what will let a replaced scan or a future provider change the bytes
without touching a book's annotations.

---

## Storage

Content-addressed: a file's SHA-256 is its identity and its path
(`library/ab/cd/abcd….pdf`). Consequences worth knowing:

- **Uploading the same file twice stores one copy.** Retrying a ZIP import that
  died halfway therefore costs no extra disk, which is what makes
  "skip duplicates" a safe default.
- **Two books can share one blob**, so deleting a book removes the file only
  once nothing references it.
- **A changed file is a different key**, so nothing can serve stale bytes.

Writes stage and rename, so an interrupted upload leaves nothing that a later
read could mistake for a complete file.

---

## ZIP import

Archives are hostile input. `zip_import.py` validates before anything is
written, and 27 tests cover the ways this goes wrong:

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

Extraction runs in the worker: a few hundred books take minutes, and a request
would time out. The upload endpoint stages the archive and returns an
`UploadBatch` the UI polls.

---

## Folders

Invariants live in the model, not in the view:

- no cycles, and no moving a folder into its own subtree
- a depth cap
- no reparenting under another user's folder
- unique names per parent — which needs **two** partial constraints, because
  PostgreSQL treats NULL parents as distinct and a single
  `UNIQUE(owner, parent, name)` would allow two "Books" at the top level
- the uniqueness applies only to live folders, so a trashed name can be reused

Trashing a folder trashes its subtree and books. Restoring brings back what was
trashed *with it*, and deliberately not something deleted separately
beforehand.

---

## What is still open

- **Per-user quotas.** There is a global max upload size and a disk floor, but
  nothing stops one user filling the disk. Fine for a household; needed before
  an instance has users who do not know each other.
- **Move to a chosen folder.** The row menu offers "move up one level"; a
  folder picker (or drag onto a folder) is the natural next step.
- **Emptying the trash automatically.** Items stay until deleted by hand.
- **Replacing a book's file** while keeping its annotations — the model
  supports it, no endpoint exposes it.
- **Resumable / chunked uploads** for very large files over a flaky link.

## Acceptance

Reworded from PRD §45, dropping the Drive criteria:

- users can upload PDFs and see them appear
- a ZIP rebuilds its folder structure exactly
- folders can be created, renamed, moved, and deleted
- deleting is reversible; permanent deletion is a separate, explicit step
- re-uploading the same archive changes nothing
- a hostile archive imports nothing dangerous
- one user cannot see or touch another's folders or books
