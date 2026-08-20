# Implementation phases

One document per phase from PRD §44, recording what each decided and why. All
seven are built; these are kept as the design record, not as current
documentation — the [README](../../README.md) describes what the system does
now.

| Phase | Document |
| --- | --- |
| 1 — Platform foundation | the repository and [deployment.md](../deployment.md) |
| 2 — Uploads, folders, storage | [02-uploads.md](02-uploads.md) |
| 3 — Library | [03-library.md](03-library.md) |
| 4 — PDF reader | [04-reader.md](04-reader.md) |
| 5 — Bookmarks, highlights, notes | [05-reading-data.md](05-reading-data.md) |
| 6 — Sharing | [06-sharing.md](06-sharing.md) |
| 7 — Hardening | [07-hardening.md](07-hardening.md) |

Phase 3 finished last rather than third, which was the right order: three of its
virtual views (Continue Reading, Recently Opened, Shared With Me) need models
that Phases 4 and 6 introduce, so finishing it early would have meant writing
them twice.

Work added after these were written is not in them — resumable uploads, storage
quotas, trash retention, conditional requests, folder previews, multi-select,
and the phone layout. Two things they describe were also removed: Google Drive
as canonical storage, and the evictable PDF cache that went with it.

## Decisions that outlive their phase

Six choices were expensive to reverse because data or licensing accumulates
behind them. All six are settled.

| Decision | Where | Outcome |
| --- | --- | --- |
| Google OAuth scope route | — | Moot. Drive was removed in favour of uploads. |
| PDF rendering library | [Phase 2](02-uploads.md) | pypdfium2 (Apache-2.0). PyMuPDF is AGPL, and swapping it after it is woven through import, search and the reader is a rewrite. |
| Where ingestion executes | [Phase 2](02-uploads.md) | A polling worker with an advisory lock. A ZIP of several hundred books cannot be extracted inside a request. |
| How PDF bytes reach the browser | [Phase 4](04-reader.md) | Django streams and honours `Range`, returning 206. Whether large reads should bypass gunicorn is now a tuning question, not a design one. |
| Highlight anchoring format | [Phase 5](05-reading-data.md) | Versioned quads in PDF user space. Once highlights exist the coordinates cannot be recomputed — the mapping depended on a viewport that is gone. |
| The deletion matrix | [Phase 6](06-sharing.md) · `library/lifecycle.py` | The table lives in that module's docstring. The load-bearing choice: un-sharing keeps other readers' annotations, deleting the book does not. |

Where the PRD was silent — the progress conflict rule, highlight anchoring, the
deletion matrix, proxy trust — these documents made a recommendation and said
why, so the choice is reviewable rather than accidental. Open items that belong
to no single phase are in the README's [Known gaps](../../README.md#known-gaps).
