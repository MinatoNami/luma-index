export interface Folder {
  id: number
  name: string
  parent: number | null
  path: string
  has_children: boolean
  book_count: number
  folder_count: number
  item_count: number
  /** Books whose covers stand in for this folder — see FolderCover. */
  preview_book_ids: number[]
  deleted_at: string | null
}

export interface BookSource {
  original_filename: string
  content_type: string
  file_size: number
  availability_status: 'available' | 'missing' | 'error'
  uploaded_at: string
}

export interface Book {
  id: number
  title: string
  folder: number | null
  path: string
  page_count: number | null
  has_text_layer: boolean | null
  visibility: 'private' | 'shared'
  thumbnail_path: string
  source: BookSource | null
  deleted_at: string | null
}

export interface UploadBatch {
  id: number
  original_filename: string
  status: 'pending' | 'running' | 'ok' | 'partial' | 'failed'
  counts: Record<string, number>
  error_summary: string
}

export interface UploadResult {
  imported: Book[]
  duplicates: number
  batches: UploadBatch[]
  errors: string[]
}

export function useLibrary() {
  const { api, ensureCsrf } = useApi()

  const folderParam = (id: number | null) => (id === null ? 'root' : String(id))

  async function listFolders(parent: number | null) {
    return await api<Folder[]>('/library/folders/', { params: { parent: folderParam(parent) } })
  }

  async function listBooks(parent: number | null, options: { search?: string; sort?: string } = {}) {
    return await api<Book[]>('/library/books/', {
      params: { folder: folderParam(parent), ...options },
    })
  }

  async function folderDetail(id: number) {
    return await api<Folder & { ancestors: Folder[] }>(`/library/folders/${id}/`)
  }

  async function createFolder(name: string, parent: number | null) {
    await ensureCsrf()
    return await api<Folder>('/library/folders/', { method: 'POST', body: { name, parent } })
  }

  async function updateFolder(id: number, changes: { name?: string; parent?: number | null }) {
    await ensureCsrf()
    return await api<Folder>(`/library/folders/${id}/`, { method: 'PATCH', body: changes })
  }

  async function updateBook(id: number, changes: { title?: string; folder?: number | null }) {
    await ensureCsrf()
    return await api<Book>(`/library/books/${id}/`, { method: 'PATCH', body: changes })
  }

  async function trashFolder(id: number) {
    await ensureCsrf()
    return await api<{ trashed: Record<string, number> }>(`/library/folders/${id}/`, {
      method: 'DELETE',
    })
  }

  async function trashBook(id: number) {
    await ensureCsrf()
    await api(`/library/books/${id}/`, { method: 'DELETE' })
  }

  async function restoreFolder(id: number) {
    await ensureCsrf()
    return await api(`/library/folders/${id}/restore/`, { method: 'POST' })
  }

  async function restoreBook(id: number) {
    await ensureCsrf()
    return await api(`/library/books/${id}/restore/`, { method: 'POST' })
  }

  async function deleteForever(kind: 'folder' | 'book', id: number) {
    await ensureCsrf()
    await api(`/library/${kind}s/${id}/?permanent=true`, { method: 'DELETE' })
  }

  async function listTrash() {
    return await api<{ folders: Folder[]; books: Book[] }>('/library/trash/')
  }

  async function upload(files: File[], folder: number | null): Promise<UploadResult> {
    await ensureCsrf()
    const form = new FormData()
    for (const file of files) form.append('files', file)
    if (folder !== null) form.append('folder', String(folder))
    // No Content-Type header: the browser must set the multipart boundary.
    return await api<UploadResult>('/library/upload/', { method: 'POST', body: form })
  }

  async function batch(id: number) {
    return await api<UploadBatch>(`/library/uploads/${id}/`)
  }

  async function storage() {
    return await api<{
      free_bytes: number
      max_upload_bytes: number
      book_count: number
      quota_bytes: number
      used_bytes: number
    }>('/library/storage/')
  }

  return {
    listFolders, listBooks, folderDetail,
    createFolder, updateFolder, updateBook,
    trashFolder, trashBook, restoreFolder, restoreBook, deleteForever, listTrash,
    upload, batch, storage,
  }
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}


export interface SharedBook {
  id: number
  title: string
  page_count: number | null
  has_text_layer: boolean | null
  visibility: 'private' | 'shared'
  thumbnail_path: string
  owner_name: string
  progress: { page: number; percentage: number; last_opened_at: string } | null
  created_at: string
}

export function useSharing() {
  const { api, ensureCsrf } = useApi()

  async function sharedWithMe() {
    return await api<SharedBook[]>('/library/shared/')
  }

  async function status(bookId: number) {
    return await api<{ visibility: 'private' | 'shared'; other_readers: number }>(
      `/library/books/${bookId}/share`)
  }

  async function setVisibility(bookId: number, visibility: 'private' | 'shared') {
    await ensureCsrf()
    return await api<{ visibility: 'private' | 'shared'; other_readers: number }>(
      `/library/books/${bookId}/share`, { method: 'POST', body: { visibility } })
  }

  return { sharedWithMe, status, setVisibility }
}
