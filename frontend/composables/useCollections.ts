export interface Collection {
  id: number
  name: string
  parent: number | null
  path: string
  book_count: number
  has_children: boolean
  created_at: string
  updated_at: string
}

export function useCollections() {
  const { api, ensureCsrf } = useApi()

  async function list(parent?: number | null) {
    return await api<Collection[]>('/library/collections/', {
      params: parent === undefined ? undefined
        : { parent: parent === null ? 'root' : String(parent) },
    })
  }

  async function detail(id: number) {
    return await api<Collection & { ancestors: Collection[] }>(`/library/collections/${id}/`)
  }

  async function create(name: string, parent: number | null = null) {
    await ensureCsrf()
    return await api<Collection>('/library/collections/', {
      method: 'POST', body: { name, parent },
    })
  }

  async function rename(id: number, name: string) {
    await ensureCsrf()
    return await api<Collection>(`/library/collections/${id}/`, {
      method: 'PATCH', body: { name },
    })
  }

  async function remove(id: number) {
    await ensureCsrf()
    await api(`/library/collections/${id}/`, { method: 'DELETE' })
  }

  async function addBook(collectionId: number, bookId: number) {
    await ensureCsrf()
    return await api<{ added: boolean }>(`/library/collections/${collectionId}/books/`, {
      method: 'POST', body: { book_id: bookId },
    })
  }

  async function removeBook(collectionId: number, bookId: number) {
    await ensureCsrf()
    await api(`/library/collections/${collectionId}/books/${bookId}/`, { method: 'DELETE' })
  }

  async function setFavourite(bookId: number, favourite: boolean) {
    await ensureCsrf()
    if (favourite) await api(`/library/books/${bookId}/favourite`, { method: 'POST' })
    else await api(`/library/books/${bookId}/favourite`, { method: 'DELETE' })
  }

  return { list, detail, create, rename, remove, addBook, removeBook, setFavourite }
}
