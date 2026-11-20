import type { HighlightColour } from '~/composables/useAnnotations'

/**
 * The notebook and reading activity: everything a reader has written, across
 * books, and how often they read. See backend/library/notebook.py and
 * activity.py for the rules; this is the client half.
 */

export interface NotebookEntry {
  kind: 'highlight' | 'note'
  id: number
  book: { id: number; title: string }
  /** 0-indexed. */
  page: number
  /** The passage, or a page note's body. */
  text: string
  /** A highlight's note. Empty for page notes. */
  note: string
  /** Empty for page notes. */
  colour: HighlightColour | ''
  created_at: string
  updated_at: string
}

export interface DailyHighlight {
  id: number
  book: { id: number; title: string }
  page: number
  text: string
  note: string
  colour: HighlightColour
}

export interface Activity {
  today: string
  /** Pages a day. 0 means no goal. */
  goal_pages: number
  today_pages: number
  streak: { current: number; longest: number }
  /** The last seven days, oldest first. */
  week: { date: string; pages: number }[]
  year: { pages: number; days: number; books_finished: number }
}

export interface NotebookFilters {
  q?: string
  kind?: 'highlight' | 'note' | ''
  colour?: HighlightColour | ''
  book?: number | null
  order?: NotebookOrder
}

/** Newest first, or the order you would meet them reading the book. */
export type NotebookOrder = 'recent' | 'page'

/** A book the reader has written on, as the notebook's book list shows it. */
export interface NotebookBook {
  id: number
  title: string
  highlights: number
  /** Page notes. */
  notes: number
  last_at: string
}

/**
 * The order a notebook lists in when nobody has chosen one.
 *
 * Across every book, newest first: that is how you find what you marked last
 * week. Within one book, page order: that is how you reread it, and how
 * Kindle's notebook lists a book.
 */
export function defaultOrder(bookId: number | null | undefined): NotebookOrder {
  return bookId ? 'page' : 'recent'
}

/**
 * A passage as it travels on the clipboard: quoted, with where it came from,
 * so a paste into a message or a note still says whose words they are.
 */
export function citation(entry: Pick<NotebookEntry, 'text' | 'book' | 'page'>): string {
  return `“${entry.text.trim()}”\n— ${entry.book.title}, page ${entry.page + 1}`
}

/**
 * When something was written, in calendar days where the reader is: "Today",
 * "Yesterday", then a date. Counted in calendar days, not 24-hour spans — a
 * note made at 11pm is "Yesterday" at 1am, not "Today".
 */
export function relativeDay(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((midnight(now) - midnight(date)) / 86_400_000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return date.toLocaleDateString(undefined, {
    day: 'numeric', month: 'short',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  })
}

/** "2 highlights · 1 note", leaving out what there is none of. */
export function countLabel(highlights: number, notes: number): string {
  const parts: string[] = []
  if (highlights) parts.push(`${highlights} ${highlights === 1 ? 'highlight' : 'highlights'}`)
  if (notes) parts.push(`${notes} ${notes === 1 ? 'note' : 'notes'}`)
  return parts.join(' · ') || 'Nothing yet'
}

interface Envelope<T> { count: number; limit: number; offset: number; results: T[] }

/**
 * Today's date where the reader is, as YYYY-MM-DD.
 *
 * Not `toISOString()`, which is UTC: in Singapore at 7am that is still
 * yesterday, and a page read over breakfast would count towards the day
 * before — which is how a streak breaks for no reason anyone can see.
 */
export function localDate(at: Date = new Date()): string {
  const y = at.getFullYear()
  const m = String(at.getMonth() + 1).padStart(2, '0')
  const d = String(at.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** How far through today's goal, 0–100. No goal is no progress to show. */
export function goalPercent(pages: number, goal: number): number {
  if (!goal || goal <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((pages / goal) * 100)))
}

/**
 * The streak, said the way a person would.
 *
 * A streak of nothing is not "0-day streak" — it is an invitation, and a
 * streak that has ended is not worth reproaching anyone over either.
 */
export function streakLabel(current: number): string {
  if (current <= 0) return 'Read today to start a streak'
  return current === 1 ? '1 day in a row' : `${current} days in a row`
}

/**
 * Bar heights for the week, as fractions of the tallest day — or of the goal,
 * if that is higher, so a goal line sits at a meaningful height and a week of
 * short days does not look like a week of full ones.
 */
export function weekScale(week: { pages: number }[], goal: number): number[] {
  const top = Math.max(goal || 0, ...week.map(d => d.pages), 1)
  return week.map(d => d.pages / top)
}

/** "Tue", from a YYYY-MM-DD, read as a local date rather than UTC midnight. */
export function weekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1).toLocaleDateString(undefined, { weekday: 'short' })
}

export function useNotebook() {
  const { api, ensureCsrf } = useApi()
  const apiUrl = useApiUrl()

  function params(filters: NotebookFilters) {
    const out: Record<string, string | number> = {}
    if (filters.q?.trim()) out.q = filters.q.trim()
    if (filters.kind) out.kind = filters.kind
    if (filters.colour) out.colour = filters.colour
    if (filters.book) out.book = filters.book
    if (filters.order) out.order = filters.order
    return out
  }

  async function books() {
    return await api<{ count: number; totals: { highlights: number; notes: number }
                       results: NotebookBook[] }>('/library/notebook/books/')
  }

  /**
   * Change what an entry says: a highlight's note, or a page note's body.
   * Through the per-book endpoints, so the notebook has no write path of its
   * own to keep in step with the reader's.
   */
  async function edit(entry: NotebookEntry, text: string): Promise<NotebookEntry> {
    await ensureCsrf()
    const base = `/library/books/${entry.book.id}`
    if (entry.kind === 'highlight') {
      const saved = await api<{ note: string; updated_at: string }>(
        `${base}/highlights/${entry.id}`, { method: 'PATCH', body: { note: text } })
      return { ...entry, note: saved.note, updated_at: saved.updated_at }
    }
    const saved = await api<{ body: string; updated_at: string }>(
      `${base}/notes/${entry.id}`, { method: 'PATCH', body: { body: text } })
    return { ...entry, text: saved.body, updated_at: saved.updated_at }
  }

  async function remove(entry: NotebookEntry): Promise<void> {
    await ensureCsrf()
    const kind = entry.kind === 'highlight' ? 'highlights' : 'notes'
    await api(`/library/books/${entry.book.id}/${kind}/${entry.id}`, { method: 'DELETE' })
  }

  async function list(filters: NotebookFilters, options: { limit?: number; offset?: number } = {}) {
    const body = await api<Envelope<NotebookEntry>>('/library/notebook/', {
      params: { ...params(filters), ...options },
    })
    return { items: body.results ?? [], total: body.count ?? 0 }
  }

  async function daily() {
    return await api<{ date: string; results: DailyHighlight[] }>('/library/notebook/daily/', {
      params: { today: localDate() },
    })
  }

  async function activity() {
    return await api<Activity>('/library/activity/', { params: { today: localDate() } })
  }

  /**
   * A download link, followed by the browser rather than fetched. Carries the
   * reader's date for the file's stamp, as everything else here does.
   */
  function exportUrl(bookId?: number | null): string {
    const query = new URLSearchParams({ today: localDate() })
    if (bookId) query.set('book', String(bookId))
    return `${apiUrl('/library/notebook/export')}?${query}`
  }

  return { list, books, daily, activity, exportUrl, edit, remove }
}
