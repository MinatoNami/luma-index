# Implementation phases

One document per phase from PRD §44. Each states its goal, the decisions to
settle *before* writing code, the data model, the API surface, the risks, and
which of the 31 MVP success criteria (§45) it proves.

| Phase | Status | Document |
| --- | --- | --- |
| 1 — Platform foundation | **Built** | see the repository and [deployment.md](../deployment.md) |
| 2 — Uploads, folders, storage | **Built** | [02-uploads.md](02-uploads.md) |
| 3 — Library | **Partly built** | [03-library.md](03-library.md) |
| 4 — PDF reader | **Built** | [04-reader.md](04-reader.md) |
| 5 — Bookmarks, highlights, notes | **Built** | [05-reading-data.md](05-reading-data.md) |
| 6 — Sharing | **Built** | [06-sharing.md](06-sharing.md) |
| 7 — Hardening | Scoped | [07-hardening.md](07-hardening.md) |

---

Phase 3 is half-done as a side effect of Phase 2 and the interface work: list,
grid and large-icon views, covers, search and sort all exist. What remains is
collections, favourites, and the virtual views — and three of those
(Continue Reading, Recently Opened, Shared With Me) need models from Phases 4
and 6, so the rest of Phase 3 is best finished after the reader rather than
before it.

## Decisions that outlive their phase

Six choices are expensive to reverse because data or licensing accumulates
behind them. Each is argued where it belongs; they are collected here so none
is discovered late.

| # | Decision | Where | Why it cannot wait |
| --- | --- | --- | --- |
| 1 | ~~Google OAuth scope route~~ | — | **Moot.** Drive was removed in favour of uploads. |
| 2 | **PDF rendering library** | [Phase 2](02-uploads.md) | Settled: pypdfium2 (Apache-2.0). PyMuPDF is AGPL, and swapping it after it is woven through import, search, and the reader is a rewrite. |
| 3 | **Where ingestion executes** | [Phase 2](02-uploads.md) | Settled: a polling worker. A ZIP of several hundred books cannot be extracted inside a request. |
| 4 | ~~How PDF bytes reach the browser~~ | [Phase 4 D1](04-reader.md) | **Settled.** The endpoint returns 206 for byte ranges and PDF.js fetches only what it needs. Whether large reads should bypass gunicorn entirely is now a tuning question, not a design one. |
| 5 | **Highlight anchoring format** | [Phase 5 D1](05-reading-data.md) | Once highlights exist, the coordinates cannot be recomputed — the mapping depended on a viewport that is gone. |
| 6 | ~~The deletion matrix~~ | [Phase 6 D1](06-sharing.md) · `library/lifecycle.py` | **Settled.** The table lives in the module docstring. The load-bearing choice: un-sharing keeps other readers' annotations, deleting the book does not. |

All six are settled. The two that were open longest — the highlight anchoring
format and the deletion matrix — are now enforced in code and covered by tests
(`library/annotations.py` and `library/lifecycle.py`).

## Dependency order

```text
Phase 1  platform          ✅ built
   │
Phase 2  uploads + folders ✅ built — Book + BookSource, which the rest assumes
   │
   ├── Phase 3  library    collections, search, virtual views
   │      │
   │   Phase 4  reader     needs a book to open
   │      │
   │   Phase 5  annotations needs the reader's text layer
   │      │
   └── Phase 6  sharing    widens every Phase 3–5 queryset
          │
       Phase 7  hardening  proves what the rest claim
```

Phases 3 and 4 can overlap once Phase 2 lands — the library is mostly backend
CRUD while the reader is mostly frontend.

## How these documents were written

From the PRD, plus what building Phase 1 exposed. Where the PRD is explicit,
these repeat it and point at the section. Where it is silent — the reading
progress conflict rule, the highlight anchoring format, the deletion matrix,
proxy trust — they make a recommendation and say why, so the choice is
reviewable rather than accidental.

Open items that do not belong to a single phase are in the README's
[Known gaps](../../README.md#known-gaps).
