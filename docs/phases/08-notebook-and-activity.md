# Phase 8 — Notebook, reading activity, quick open

**Goal:** make what a reader has written, and how often they read, visible
outside the one book it happened in — the PRD §43 items "global highlight
search", "annotation export", "reading statistics" and "goals/streaks" — without
crossing §42's non-goals (no AI, no OCR, no EPUB, no new services).

**Depends on:** Phase 5 (annotations), Phase 4 (progress writes).

## What comparable tools do

A survey of the self-hosted servers this is most often compared with, and of
the reading products people move to them from. The question was which features
recur — not which are clever — and which of those fit a household PDF library.

| Product | What it does well that LumaIndex lacked |
| --- | --- |
| **Kindle** | A notebook of every highlight; reading insights and streaks |
| **Apple Books** | A daily reading goal with a streak; a Notes view per book |
| **Readwise / Reader** | Highlights resurfaced daily; export to Obsidian, Notion, Markdown |
| **Zotero 7** | Annotations gathered into notes; Markdown export that links back to the page |
| **StoryGraph** | Pages and books finished per year |
| **Kavita** | Reading stats; smart filters saved to the sidebar |
| **BookLore / Grimmory** | Rule-based "magic shelves"; stats; metadata fetch; KOReader and Kobo sync |
| **Calibre-Web** | OPDS feeds, send-to-Kindle, metadata editing |
| **Linear, Notion, Obsidian, Raycast** | One box behind ⌘K that reaches anything by name |

Four recur across nearly all of them and fit without new infrastructure: a
cross-book notebook, an export, a goal with a streak, and quick open. That is
what was built. The rest is under *Not built*, below.

## Decisions

**The notebook is one SQL UNION, paged by the database.** Highlights and page
notes are different tables, and the list interleaves them newest first. Merging
two lists in Python makes `offset=2000` cost two thousand rows from each; a
`UNION ALL` ordered by `created_at` lets PostgreSQL do the paging and the
`count`. Django 5.2 keeps `values()` in the order given, which is what makes the
two halves' columns line up. `library/notebook.py`

**Same permission rule as the per-book endpoints, applied once.** A reader's own
annotations, on books they can still open. Un-sharing a book hides another
reader's notes on it from the notebook exactly as the per-book list 404s, and a
trashed book's notes drop out. The notebook is a second door to the same rows,
so it is tested as one.

**Export is Markdown, page by page in reading order.** It is what Obsidian,
Logseq, Notion and a text editor all take without a plugin, which is why Readwise
and Zotero export to it. Reading order rather than creation order, so the file
reads like the book did. Notes pass through as written — they are the reader's
own and may already be Markdown. Slugified ASCII filename, `no-store`.

**Today's highlights hold no state.** The order is `md5(id || user || date)`, so
the three picks hold still all day — a reload does not reshuffle them — and are a
different three tomorrow. Readwise's spaced repetition needs a schedule per
highlight; this is the useful half of it without a table that can drift.

**A page counts when you arrive on it.** `ReadingDay(user, book, day, pages[])`
records distinct pages, written by the progress endpoint only when the position
*moved*. Reopening a book where you left off is not reading; sitting on a page
while the client re-reports it is one page; scrolling back over a spread is not
twenty; jumping from the contents to chapter nine is one page, not two hundred.
Minutes were the alternative (Apple Books uses them), but a tab left open
overnight is eight hours of "reading", and pages need no idle detection.

**The day is the reader's, not the server's.** The server keeps UTC, which in
Singapore ends "today" at eight in the morning — a streak that breaks for no
reason anyone can see. The browser sends its own date (`local_date` on progress
writes, `today` on reads); the server accepts it only within a day of its own,
which every real time zone is, and otherwise uses its own.

**A streak is not broken by a day still in progress.** At breakfast, having read
yesterday, you are on a streak. It counts back from today if you have read today
and from yesterday if not, and ends only when a whole day passes.

**A goal is opt-in.** `daily_page_goal` defaults to 0, meaning none — a target
nobody chose is a nag. It is a column rather than a key in `preferences`, so the
serializer can bound it (0–1000).

**`finished_at` is the first time, kept.** Going back to reread a chapter and
reaching the end again does not move it. The migration backfills it from
`updated_at` for books already read, so this year's count is not zero on the day
of the upgrade.

**Quick open lives in the shell, not the reader.** ⌘K / Ctrl K on every page with
the rail; the reader keeps its keys for reading. It is an ARIA combobox: focus
stays in the input and `aria-activedescendant` follows the arrow keys. It finds
titles, places, and hands a query to search-inside (`/library?q=`) or the
notebook (`/notebook?q=`).

**The week chart is one series.** One hue, no legend (the heading names it), bars
rounded only at the data end, a solid hairline at the goal, a hover tooltip per
day, and the seven numbers in a visually hidden table. `--chart-bar` is
`--accent` in light mode and a step deeper in dark, where `--accent` sits above
the lightness band a chart mark should occupy.

## Not built

| Idea | Seen in | Why not yet |
| --- | --- | --- |
| Smart shelves (saved rule-based filters) | BookLore, Kavita | Needs metadata worth filtering on first — today a book has a title and a folder. |
| Authors, series, tags, ratings | Calibre-Web, BookLore | PRD §43. A model and an editing UI; the natural next step, and smart shelves follow from it. |
| OPDS feed | Calibre-Web, Kavita, Komga | E-reader apps cannot hold a session cookie; it needs per-device app passwords, which is a security design of its own. |
| KOReader / Kobo progress sync | BookLore, Calibre-Web | Same authentication question as OPDS. |
| "Want to read" and "mark as finished" | Kindle, Apple Books, StoryGraph | Small; `finished_at` is the half of it that exists now. |
| Time left in book or chapter | Kindle | Needs a reading speed, which `ReadingDay` can now supply. |
| Spaced-repetition review | Readwise | A per-highlight schedule; today's highlights are the stateless half. |
| AI summaries, Q&A, semantic search | Readwise, Reader | PRD §42 non-goals. |
