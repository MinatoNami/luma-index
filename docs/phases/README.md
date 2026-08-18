# Implementation phases

One document per phase from PRD §44. Each states its goal, the decisions to
settle *before* writing code, the data model, the API surface, the risks, and
which of the 31 MVP success criteria (§45) it proves.

| Phase | Status | Document |
| --- | --- | --- |
| 1 — Platform foundation | **Built** | see the repository and [deployment.md](../deployment.md) |
| 2 — Google Drive | **Backend built** | [02-google-drive.md](02-google-drive.md) |
| 3 — Library | Scoped | [03-library.md](03-library.md) |
| 4 — PDF reader | Scoped | [04-reader.md](04-reader.md) |
| 5 — Bookmarks, highlights, notes | Scoped | [05-reading-data.md](05-reading-data.md) |
| 6 — Sharing | Scoped | [06-sharing.md](06-sharing.md) |
| 7 — Hardening | Scoped | [07-hardening.md](07-hardening.md) |

---

## Decisions that outlive their phase

Six choices are expensive to reverse because data or licensing accumulates
behind them. Each is argued where it belongs; they are collected here so none
is discovered late.

| # | Decision | Where | Why it cannot wait |
| --- | --- | --- | --- |
| 1 | **Google OAuth scope route** | [Phase 2 D1](02-google-drive.md) · [google-oauth.md](../google-oauth.md) | Restricted scopes need verification plus a paid security assessment; Testing mode expires every refresh token after 7 days. Gates all of Phase 2. |
| 2 | **PDF rendering library** | [Phase 2 D2](02-google-drive.md) | PyMuPDF is AGPL. Swapping it after it is woven through import, search, and the reader is a rewrite. |
| 3 | **Where sync executes** | [Phase 2 D3](02-google-drive.md) | A large first import cannot run inside a request. Choosing wrong means retrofitting a worker later. |
| 4 | **How PDF bytes reach the browser** | [Phase 4 D1](04-reader.md) | Range support and not blocking a worker per download. Shapes the content endpoint's signature. |
| 5 | **Highlight anchoring format** | [Phase 5 D1](05-reading-data.md) | Once highlights exist, the coordinates cannot be recomputed — the mapping depended on a viewport that is gone. |
| 6 | **The deletion matrix** | [Phase 6 D1](06-sharing.md) | §33 leaves it undefined. Every FK needs an explicit `on_delete`, and getting it wrong destroys other people's annotations. |

If you only settle a few things before writing Phase 2, settle 1, 2 and 6 —
they are the ones whose cost grows fastest.

## Dependency order

```text
Phase 1  platform          ✅ built
   │
Phase 2  Google Drive      Book + BookSource — everything else assumes these
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

Open items that do not belong to a single phase are in
[open-questions.md](../open-questions.md).
