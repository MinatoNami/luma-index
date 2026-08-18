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

export function useAnnotations(bookId: MaybeRefOrGetter<number>) {
  const { api, ensureCsrf } = useApi()
  const base = () => `/library/books/${toValue(bookId)}`

  const bookmarks = ref<Bookmark[]>([])
  const highlights = ref<Highlight[]>([])
  const notes = ref<PageNote[]>([])

  async function loadAll() {
    const [b, h, n] = await Promise.all([
      api<Bookmark[]>(`${base()}/bookmarks`),
      api<Highlight[]>(`${base()}/highlights`),
      api<PageNote[]>(`${base()}/notes`),
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
