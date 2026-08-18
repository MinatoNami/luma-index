<script setup lang="ts">
import { formatBytes, type Book, type Folder, type UploadBatch } from '~/composables/useLibrary'

const library = useLibrary()
const { user, logout } = useAuth()
const route = useRoute()
const router = useRouter()

const currentId = computed(() => {
  const raw = route.query.folder
  return raw === undefined || raw === 'root' ? null : Number(raw)
})

const folders = ref<Folder[]>([])
const books = ref<Book[]>([])
const breadcrumbs = ref<Folder[]>([])
const currentFolder = ref<Folder | null>(null)
const search = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const dragging = ref(false)
const batches = ref<UploadBatch[]>([])

// One dialog driver for rename, new-folder, move and delete confirmation.
const dialog = ref<{
  title: string; label?: string; value?: string; confirmLabel?: string
  danger?: boolean; message?: string; run: (value: string) => Promise<void>
} | null>(null)

const fileInput = ref<HTMLInputElement | null>(null)

async function load() {
  busy.value = true
  error.value = ''
  try {
    const [folderList, bookList] = await Promise.all([
      library.listFolders(currentId.value),
      library.listBooks(currentId.value, search.value ? { search: search.value } : {}),
    ])
    folders.value = folderList
    books.value = bookList

    if (currentId.value === null) {
      breadcrumbs.value = []
      currentFolder.value = null
    } else {
      const detail = await library.folderDetail(currentId.value)
      breadcrumbs.value = detail.ancestors
      currentFolder.value = detail
    }
  } catch (err: any) {
    error.value = err?.data?.detail || 'Could not load this folder.'
  } finally {
    busy.value = false
  }
}

watch(() => route.query.folder, load)
watch(search, () => load())
onMounted(load)

function open(folder: Folder) {
  router.push({ query: { folder: String(folder.id) } })
}

function goTo(id: number | null) {
  router.push({ query: id === null ? {} : { folder: String(id) } })
}

async function act(work: () => Promise<unknown>, message = '') {
  busy.value = true
  error.value = ''
  try {
    await work()
    notice.value = message
    await load()
  } catch (err: any) {
    error.value = err?.data?.detail || 'That did not work.'
  } finally {
    busy.value = false
    dialog.value = null
  }
}

// -- upload ---------------------------------------------------------------- //

async function submitFiles(files: File[]) {
  if (!files.length) return
  busy.value = true
  error.value = ''
  try {
    const result = await library.upload(files, currentId.value)
    const parts: string[] = []
    if (result.imported.length) parts.push(`${result.imported.length} added`)
    if (result.duplicates) parts.push(`${result.duplicates} already here`)
    if (result.batches.length) parts.push(`${result.batches.length} archive(s) queued`)
    notice.value = parts.join(', ') || 'Nothing to add.'
    if (result.errors.length) error.value = result.errors.join(' · ')
    if (result.batches.length) {
      batches.value = result.batches
      pollBatches()
    }
    await load()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Upload failed.'
  } finally {
    busy.value = false
  }
}

let pollTimer: ReturnType<typeof setTimeout> | null = null

async function pollBatches() {
  if (pollTimer) clearTimeout(pollTimer)
  const updated = await Promise.all(batches.value.map(b => library.batch(b.id).catch(() => b)))
  batches.value = updated
  if (updated.some(b => b.status === 'pending' || b.status === 'running')) {
    pollTimer = setTimeout(pollBatches, 1500)
  } else {
    await load()   // extraction finished; the folders now exist
  }
}

onBeforeUnmount(() => pollTimer && clearTimeout(pollTimer))

function onDrop(event: DragEvent) {
  dragging.value = false
  submitFiles(Array.from(event.dataTransfer?.files ?? []))
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  submitFiles(Array.from(input.files ?? []))
  input.value = ''
}

// -- row actions ------------------------------------------------------------ //

function newFolder() {
  dialog.value = {
    title: 'New folder', label: 'Name', value: 'Untitled folder', confirmLabel: 'Create',
    run: async name => { await library.createFolder(name, currentId.value) },
  }
}

function renameFolder(folder: Folder) {
  dialog.value = {
    title: 'Rename folder', label: 'Name', value: folder.name, confirmLabel: 'Rename',
    run: async name => { await library.updateFolder(folder.id, { name }) },
  }
}

function renameBook(book: Book) {
  dialog.value = {
    title: 'Rename', label: 'Title', value: book.title, confirmLabel: 'Rename',
    run: async title => { await library.updateBook(book.id, { title }) },
  }
}

function moveUp(item: Folder | Book, kind: 'folder' | 'book') {
  const destination = currentFolder.value?.parent ?? null
  return act(
    () => kind === 'folder'
      ? library.updateFolder(item.id, { parent: destination })
      : library.updateBook(item.id, { folder: destination }),
    'Moved up one level.',
  )
}

function deleteFolder(folder: Folder) {
  dialog.value = {
    title: `Move "${folder.name}" to trash?`,
    message: folder.book_count || folder.has_children
      ? 'Everything inside goes with it. You can restore it from the trash.'
      : 'You can restore it from the trash.',
    confirmLabel: 'Move to trash', danger: true,
    run: async () => { await library.trashFolder(folder.id) },
  }
}

function deleteBook(book: Book) {
  dialog.value = {
    title: `Move "${book.title}" to trash?`,
    message: 'You can restore it from the trash.',
    confirmLabel: 'Move to trash', danger: true,
    run: async () => { await library.trashBook(book.id) },
  }
}

function folderActions(folder: Folder) {
  return [
    { label: 'Rename', run: () => renameFolder(folder) },
    ...(currentId.value !== null
      ? [{ label: 'Move up one level', run: () => moveUp(folder, 'folder') }]
      : []),
    { label: 'Move to trash', danger: true, run: () => deleteFolder(folder) },
  ]
}

function bookActions(book: Book) {
  return [
    { label: 'Rename', run: () => renameBook(book) },
    { label: 'Download', run: () => window.open(`/api/library/books/${book.id}/content`, '_blank') },
    ...(currentId.value !== null
      ? [{ label: 'Move up one level', run: () => moveUp(book, 'book') }]
      : []),
    { label: 'Move to trash', danger: true, run: () => deleteBook(book) },
  ]
}

const isEmpty = computed(() => !busy.value && !folders.value.length && !books.value.length)
</script>

<template>
  <main class="wrap" @dragover.prevent="dragging = true" @dragleave.self="dragging = false"
        @drop.prevent="onDrop">
    <header>
      <h1>LumaIndex</h1>
      <div class="who">
        <NuxtLink to="/trash">Trash</NuxtLink>
        <span>{{ user?.display_name || user?.email }}</span>
        <button class="secondary" type="button" @click="logout">Sign out</button>
      </div>
    </header>

    <nav class="crumbs" aria-label="Breadcrumb">
      <button type="button" class="crumb" @click="goTo(null)">My library</button>
      <template v-for="crumb in breadcrumbs" :key="crumb.id">
        <span aria-hidden="true">/</span>
        <button type="button" class="crumb" @click="goTo(crumb.id)">{{ crumb.name }}</button>
      </template>
      <template v-if="currentFolder">
        <span aria-hidden="true">/</span>
        <span class="crumb current">{{ currentFolder.name }}</span>
      </template>
    </nav>

    <div class="toolbar">
      <input v-model="search" type="search" placeholder="Search titles…" aria-label="Search" />
      <div class="spacer" />
      <button class="secondary" type="button" :disabled="busy" @click="newFolder">
        New folder
      </button>
      <button type="button" :disabled="busy" @click="fileInput?.click()">Upload</button>
      <input ref="fileInput" class="hidden-input" type="file" multiple
             accept="application/pdf,.pdf,.zip,application/zip" @change="onPick" />
    </div>

    <p v-if="error" class="notice bad" role="alert">{{ error }}</p>
    <p v-else-if="notice" class="notice" role="status">{{ notice }}</p>

    <ul v-if="batches.length" class="batches">
      <li v-for="batch in batches" :key="batch.id">
        <strong>{{ batch.original_filename }}</strong>
        <span class="muted">
          {{ batch.status === 'pending' ? 'queued' : batch.status }}
          <template v-if="batch.counts.discovered">
            — {{ batch.counts.imported }}/{{ batch.counts.discovered }} imported
            <template v-if="batch.counts.skipped_duplicate">
              , {{ batch.counts.skipped_duplicate }} already here
            </template>
          </template>
        </span>
      </li>
    </ul>

    <div v-if="dragging" class="dropzone">Drop PDFs or a ZIP to add them here</div>

    <table v-if="!isEmpty" class="listing">
      <thead>
        <tr><th scope="col">Name</th><th scope="col">Size</th><th scope="col">Pages</th>
          <th scope="col"><span class="sr-only">Actions</span></th></tr>
      </thead>
      <tbody>
        <tr v-for="folder in folders" :key="`f${folder.id}`">
          <td>
            <button class="name" type="button" @click="open(folder)">
              <span aria-hidden="true">📁</span> {{ folder.name }}
            </button>
          </td>
          <td class="muted">{{ folder.book_count }} item(s)</td>
          <td />
          <td class="actions"><RowMenu :actions="folderActions(folder)" /></td>
        </tr>
        <tr v-for="book in books" :key="`b${book.id}`">
          <td>
            <a class="name" :href="`/api/library/books/${book.id}/content`" target="_blank">
              <span aria-hidden="true">📄</span> {{ book.title }}
            </a>
            <span v-if="book.source?.availability_status !== 'available'" class="warn">
              file unavailable
            </span>
          </td>
          <td class="muted">{{ book.source ? formatBytes(book.source.file_size) : '—' }}</td>
          <td class="muted">{{ book.page_count ?? '…' }}</td>
          <td class="actions"><RowMenu :actions="bookActions(book)" /></td>
        </tr>
      </tbody>
    </table>

    <div v-if="isEmpty" class="empty panel">
      <h2>{{ search ? 'Nothing matches that' : 'This folder is empty' }}</h2>
      <p v-if="!search">
        Drag PDFs here, or upload a ZIP — its folders are recreated as you had them.
      </p>
    </div>

    <PromptDialog v-if="dialog" :title="dialog.title" :label="dialog.label"
                  :model-value="dialog.value" :confirm-label="dialog.confirmLabel"
                  :danger="dialog.danger" :message="dialog.message"
                  @cancel="dialog = null"
                  @confirm="value => act(() => dialog!.run(value))" />
  </main>
</template>

<style scoped>
.wrap { max-width: 62rem; margin: 0 auto; padding: 1.5rem; min-height: 100dvh; }
header { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
         justify-content: space-between; margin-bottom: 1rem; }
h1 { font-size: 1.35rem; margin: 0; }
.who { display: flex; align-items: center; gap: 1rem; color: var(--muted); font-size: 0.9rem; }
.crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem;
          color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; }
.crumb { background: none; border: 0; color: var(--accent); padding: 0.2rem 0.25rem;
         min-height: 0; font-size: 0.9rem; border-radius: 4px; }
.crumb.current { color: var(--text); }
.toolbar { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;
           margin-bottom: 1rem; }
.toolbar input[type="search"] { width: min(18rem, 100%); padding: 0.6rem 0.8rem;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
  color: var(--text); font: inherit; }
.spacer { flex: 1; }
.hidden-input { display: none; }
.notice { border-radius: 8px; padding: 0.7rem 1rem; font-size: 0.9rem;
          background: color-mix(in srgb, var(--accent) 12%, transparent); }
.notice.bad { background: color-mix(in srgb, var(--danger) 14%, transparent);
              color: var(--danger); }
.batches { list-style: none; margin: 0 0 1rem; padding: 0; display: grid; gap: 0.35rem; }
.batches li { font-size: 0.9rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.dropzone { border: 2px dashed var(--accent); border-radius: var(--radius);
            padding: 2.5rem; text-align: center; color: var(--accent); margin-bottom: 1rem; }
.listing { width: 100%; border-collapse: collapse; }
.listing th { text-align: left; font-size: 0.8rem; color: var(--muted); font-weight: 500;
              padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
.listing td { padding: 0.4rem 0.75rem; border-bottom: 1px solid var(--border);
              vertical-align: middle; }
.listing td.actions { width: 3rem; text-align: right; }
.name { background: none; border: 0; color: var(--text); font: inherit; text-align: left;
        padding: 0.35rem 0; min-height: 36px; text-decoration: none; display: inline-block; }
.name:hover { color: var(--accent); }
.muted { color: var(--muted); font-size: 0.9rem; white-space: nowrap; }
.warn { color: var(--danger); font-size: 0.8rem; margin-left: 0.5rem; }
.empty { text-align: center; padding: 3rem 1.5rem; }
.empty h2 { font-size: 1rem; margin: 0 0 0.5rem; }
.empty p { color: var(--muted); font-size: 0.9rem; margin: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

@media (max-width: 40rem) {
  .listing th:nth-child(2), .listing td:nth-child(2),
  .listing th:nth-child(3), .listing td:nth-child(3) { display: none; }
}
</style>
