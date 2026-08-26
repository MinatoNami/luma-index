export interface Bookmark {
  id: number
  page: number
  page_fraction: number
  label: string
  created_at: string
}

export interface Quad { x1: number; y1: number; x2: number; y2: number }

export interface PositionData {
  v: number
  quads: Quad[]
  text_offsets?: { start: number; end: number }
}

export type HighlightColour = 'yellow' | 'green' | 'blue' | 'pink'

export interface Highlight {
  id: number
  page: number
  selected_text: string
  position_data: PositionData
  colour: HighlightColour
  note: string
  created_at: string
  updated_at: string
}

export interface PageNote {
  id: number
  page: number
  body: string
  created_at: string
  updated_at: string
}

interface Envelope<T> { count: number; limit: number; offset: number; results: T[] }

export function useAnnotations(bookId: MaybeRefOrGetter<number>) {
  const { api, ensureCsrf } = useApi()
  const base = () => `/library/books/${toValue(bookId)}`

  /**
   * Every annotation, however many pages that takes.
   *
   * The list endpoints are bounded, and the reader draws overlays by filtering
   * the highlights it holds by page number — so stopping at the first slice
   * would not show a short list, it would stop showing highlights on later
   * pages altogether. What the bound is for is the size of one response, not
   * the size of what the client ends up with.
   */
  async function fetchAll<T>(path: string): Promise<T[]> {
    const first = await api<Envelope<T>>(path)
    const all = [...first.results]
    // Guard on the slice being non-empty as well as on the count: a server
    // that returned an empty page forever would otherwise spin here.
    while (all.length < first.count) {
      const next = await api<Envelope<T>>(path, { params: { offset: all.length } })
      if (!next.results.length) break
      all.push(...next.results)
    }
    return all
  }

  const bookmarks = ref<Bookmark[]>([])
  const highlights = ref<Highlight[]>([])
  const notes = ref<PageNote[]>([])

  async function loadAll() {
    const [b, h, n] = await Promise.all([
      fetchAll<Bookmark>(`${base()}/bookmarks`),
      fetchAll<Highlight>(`${base()}/highlights`),
      fetchAll<PageNote>(`${base()}/notes`),
    ])
    bookmarks.value = b
    highlights.value = h
    notes.value = n
  }

  async function addBookmark(page: number, label = '') {
    await ensureCsrf()
    const created = await api<Bookmark>(`${base()}/bookmarks`, {
      method: 'POST', body: { page, label },
    })
    bookmarks.value = [...bookmarks.value, created].sort((a, b) => a.page - b.page)
    return created
  }

  async function removeBookmark(id: number) {
    await ensureCsrf()
    await api(`${base()}/bookmarks/${id}`, { method: 'DELETE' })
    bookmarks.value = bookmarks.value.filter(b => b.id !== id)
  }

  async function addHighlight(payload: {
    page: number; selected_text: string; position_data: PositionData
    colour: HighlightColour
  }) {
    await ensureCsrf()
    const created = await api<Highlight>(`${base()}/highlights`, {
      method: 'POST', body: payload,
    })
    highlights.value = [...highlights.value, created]
    return created
  }

  async function updateHighlight(id: number, changes: Partial<Pick<Highlight, 'colour' | 'note'>>) {
    await ensureCsrf()
    const updated = await api<Highlight>(`${base()}/highlights/${id}`, {
      method: 'PATCH', body: changes,
    })
    highlights.value = highlights.value.map(h => (h.id === id ? updated : h))
    return updated
  }

  async function removeHighlight(id: number) {
    await ensureCsrf()
    await api(`${base()}/highlights/${id}`, { method: 'DELETE' })
    highlights.value = highlights.value.filter(h => h.id !== id)
  }

  async function addNote(page: number, body: string) {
    await ensureCsrf()
    const created = await api<PageNote>(`${base()}/notes`, { method: 'POST', body: { page, body } })
    notes.value = [...notes.value, created]
    return created
  }

  async function updateNote(id: number, body: string) {
    await ensureCsrf()
    const updated = await api<PageNote>(`${base()}/notes/${id}`, {
      method: 'PATCH', body: { body },
    })
    notes.value = notes.value.map(n => (n.id === id ? updated : n))
    return updated
  }

  async function removeNote(id: number) {
    await ensureCsrf()
    await api(`${base()}/notes/${id}`, { method: 'DELETE' })
    notes.value = notes.value.filter(n => n.id !== id)
  }

  const bookmarkedPages = computed(() => new Set(bookmarks.value.map(b => b.page)))

  return {
    bookmarks, highlights, notes, bookmarkedPages,
    loadAll,
    addBookmark, removeBookmark,
    addHighlight, updateHighlight, removeHighlight,
    addNote, updateNote, removeNote,
  }
}
