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
  const { api } = useApi()
  const apiUrl = useApiUrl()

  function params(filters: NotebookFilters) {
    const out: Record<string, string | number> = {}
    if (filters.q?.trim()) out.q = filters.q.trim()
    if (filters.kind) out.kind = filters.kind
    if (filters.colour) out.colour = filters.colour
    if (filters.book) out.book = filters.book
    return out
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

  return { list, daily, activity, exportUrl }
}
