<script setup lang="ts">
import { formatBytes, type Book, type Folder, type UploadBatch } from '~/composables/useLibrary'
import type { ViewMode } from '~/components/ViewToggle.vue'

const library = useLibrary()
const { user, logout } = useAuth()
const route = useRoute()
const router = useRouter()

const currentId = computed(() => {
  const raw = route.query.folder
  return raw === undefined || raw === 'root' ? null : Number(raw)
})

const search = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const dragging = ref(false)
const batches = ref<UploadBatch[]>([])

// Remembered locally. PRD §24 wants view preferences on UserSettings so they
// follow a reader between devices; that lands with the reader.
const view = useState<ViewMode>('library-view', () => 'list')

const dialog = ref<{
  title: string; label?: string; value?: string; confirmLabel?: string
  danger?: boolean; message?: string; run: (value: string) => Promise<void>
} | null>(null)

const fileInput = ref<HTMLInputElement | null>(null)
let dragDepth = 0

// What is being moved, if anything.
const moving = ref<{ kind: 'folder' | 'book'; id: number; name: string
                     currentFolder: number | null } | null>(null)
const moveError = ref('')

// -- drag and drop ---------------------------------------------------------- //
// Two different drops land on a folder: files from the computer, which upload
// into it, and a row from the page, which moves. They are told apart by whether
// the drop carries files.
const DRAG_TYPE = 'application/x-lumaindex'
const dragPayload = ref<{ kind: 'folder' | 'book'; id: number } | null>(null)
const dropTarget = ref<number | null | 'none'>('none')

function onRowDragStart(event: DragEvent, kind: 'folder' | 'book', id: number) {
  dragPayload.value = { kind, id }
  event.dataTransfer?.setData(DRAG_TYPE, JSON.stringify({ kind, id }))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onRowDragEnd() {
  dragPayload.value = null
  dropTarget.value = 'none'
}

function canDropOn(folder: Folder): boolean {
  const dragged = dragPayload.value
  // A folder cannot be dropped into itself. Deeper cycles are the server's
  // call, and its message is shown if it refuses.
  return !(dragged?.kind === 'folder' && dragged.id === folder.id)
}

function onFolderDragOver(event: DragEvent, folder: Folder) {
  if (!canDropOn(folder)) return
  event.preventDefault()
  event.stopPropagation()
  dropTarget.value = folder.id
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes('Files') ? 'copy' : 'move'
  }
}

async function onFolderDrop(event: DragEvent, folder: Folder) {
  event.preventDefault()
  event.stopPropagation()
  dropTarget.value = 'none'
  dragDepth = 0
  dragging.value = false

  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length) {
    await submitFiles(files, folder.id)
    return
  }

  const raw = event.dataTransfer?.getData(DRAG_TYPE)
  const dragged = raw ? JSON.parse(raw) : dragPayload.value
  if (!dragged || !canDropOn(folder)) return

  // Resolve the name so the confirmation names what moved, rather than
  // reading as an empty pair of quotes.
  const name = dragged.kind === 'folder'
    ? folders.value.find(f => f.id === dragged.id)?.name ?? 'folder'
    : books.value.find(b => b.id === dragged.id)?.title ?? 'book'

  moving.value = { kind: dragged.kind, id: dragged.id, name,
                   currentFolder: currentId.value }
  await completeMove(folder.id)
}

function startMove(item: Folder | Book, kind: 'folder' | 'book') {
  moveError.value = ''
  moving.value = {
    kind,
    id: item.id,
    name: kind === 'folder' ? (item as Folder).name : (item as Book).title,
    currentFolder: kind === 'folder' ? (item as Folder).parent : (item as Book).folder,
  }
}

async function completeMove(destination: number | null) {
  const item = moving.value
  if (!item) return
  busy.value = true
  moveError.value = ''
  try {
    if (item.kind === 'folder') await library.updateFolder(item.id, { parent: destination })
    else await library.updateBook(item.id, { folder: destination })
    moving.value = null
    notice.value = `Moved “${item.name}”.`
    await load({ quiet: true })
  } catch (err: any) {
    // The server owns the cycle and depth rules; showing its message avoids
    // restating them here and getting them subtly different.
    moveError.value = err?.data?.detail || 'That move was not allowed.'
  } finally {
    busy.value = false
  }
}

// The middleware seeds this from the account's saved preference. Changing it
// here is a per-session override; Settings is where it is saved for good.
watch(view, value => import.meta.client && localStorage.setItem('lumaindex-view', value))

// Fetched during SSR, not in onMounted. Loading in onMounted meant the server
// always rendered the skeleton — so every visit flashed placeholders before the
// real content, and the Nuxt server was doing no useful work.
const { data, pending, error: loadError, refresh: reload } = await useAsyncData(
  'library-folder',
  async () => {
    const [folderList, bookList] = await Promise.all([
      library.listFolders(currentId.value),
      library.listBooks(currentId.value, search.value ? { search: search.value } : {}),
    ])
    const detail = currentId.value === null
      ? null
      : await library.folderDetail(currentId.value)
    return { folders: folderList, books: bookList, detail }
  },
  { watch: [currentId, search], default: () => ({ folders: [], books: [], detail: null }) },
)

// Surfaced rather than swallowed: a failed fetch used to render as an empty
// folder, which is indistinguishable from a folder that really is empty.
watch(loadError, (failure) => {
  if (failure) {
    const f = failure as any
    error.value = f?.data?.detail || f?.message
      || `Could not load this folder (${f?.statusCode ?? 'error'}).`
  }
}, { immediate: true })

const folders = computed<Folder[]>(() => data.value?.folders ?? [])
const books = computed<Book[]>(() => data.value?.books ?? [])
const currentFolder = computed<Folder | null>(() => data.value?.detail ?? null)
const breadcrumbs = computed<Folder[]>(() => data.value?.detail?.ancestors ?? [])
// Only a first load shows placeholders; a background refresh must not blank the
// screen the user is already reading.
const loading = computed(() => pending.value && !data.value?.folders.length
  && !data.value?.books.length)

async function load(_options: { quiet?: boolean } = {}) {
  error.value = ''
  try {
    await reload()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Could not load this folder.'
  }
}

// Covers are rendered after upload, so poll briefly while any are missing.
let coverTimer: ReturnType<typeof setTimeout> | null = null
watch(books, (list) => {
  if (coverTimer) clearTimeout(coverTimer)
  if (list.some(b => !b.thumbnail_path)) {
    coverTimer = setTimeout(() => load({ quiet: true }), 2500)
  }
})
onBeforeUnmount(() => {
  if (coverTimer) clearTimeout(coverTimer)
  if (pollTimer) clearTimeout(pollTimer)
})

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
    await load({ quiet: true })
  } catch (err: any) {
    error.value = err?.data?.detail || 'That did not work.'
  } finally {
    busy.value = false
    dialog.value = null
  }
}

// -- upload ---------------------------------------------------------------- //

async function submitFiles(files: File[], destination: number | null = currentId.value) {
  if (!files.length) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await library.upload(files, destination)
    const parts: string[] = []
    if (result.imported.length) parts.push(`${result.imported.length} added`)
    if (result.duplicates) parts.push(`${result.duplicates} already here`)
    if (result.batches.length) parts.push(`${result.batches.length} archive queued`)
    notice.value = parts.join(' · ') || 'Nothing to add.'
    if (result.errors.length) error.value = result.errors.join(' · ')
    if (result.batches.length) {
      batches.value = result.batches
      pollBatches()
    }
    await load({ quiet: true })
  } catch (err: any) {
    error.value = err?.data?.detail || 'Upload failed.'
  } finally {
    busy.value = false
  }
}

let pollTimer: ReturnType<typeof setTimeout> | null = null

async function pollBatches() {
  if (pollTimer) clearTimeout(pollTimer)
  batches.value = await Promise.all(batches.value.map(b => library.batch(b.id).catch(() => b)))
  if (batches.value.some(b => b.status === 'pending' || b.status === 'running')) {
    pollTimer = setTimeout(pollBatches, 1200)
  } else {
    await load({ quiet: true })
  }
}

function onDrop(event: DragEvent) {
  dragDepth = 0
  dragging.value = false
  submitFiles(Array.from(event.dataTransfer?.files ?? []))
}
// Counted, because dragging over a child element fires dragleave on the parent.
function onDragEnter() { dragDepth += 1; dragging.value = true }
function onDragLeave() { dragDepth -= 1; if (dragDepth <= 0) dragging.value = false }

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  submitFiles(Array.from(input.files ?? []))
  input.value = ''
}

// -- actions ---------------------------------------------------------------- //

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
  return act(() => kind === 'folder'
    ? library.updateFolder(item.id, { parent: destination })
    : library.updateBook(item.id, { folder: destination }), 'Moved up one level.')
}
function deleteFolder(folder: Folder) {
  dialog.value = {
    title: `Move “${folder.name}” to trash?`,
    message: folder.book_count || folder.has_children
      ? 'Everything inside goes with it. You can restore it from the trash.'
      : 'You can restore it from the trash.',
    confirmLabel: 'Move to trash', danger: true,
    run: async () => { await library.trashFolder(folder.id) },
  }
}
function deleteBook(book: Book) {
  dialog.value = {
    title: `Move “${book.title}” to trash?`,
    message: 'You can restore it from the trash.',
    confirmLabel: 'Move to trash', danger: true,
    run: async () => { await library.trashBook(book.id) },
  }
}

function folderActions(folder: Folder) {
  return [
    { label: 'Rename', icon: 'pencil', run: () => renameFolder(folder) },
    { label: 'Move to…', icon: 'folder', run: () => startMove(folder, 'folder') },
    ...(currentId.value !== null
      ? [{ label: 'Move up one level', icon: 'arrow-up', run: () => moveUp(folder, 'folder') }]
      : []),
    { label: 'Move to trash', icon: 'trash', danger: true, run: () => deleteFolder(folder) },
  ]
}
async function toggleShare(book: Book) {
  const sharing = useSharing()
  const state = await sharing.status(book.id)
  const next = state.visibility === 'shared' ? 'private' : 'shared'

  dialog.value = {
    title: next === 'shared' ? `Share “${book.title}”?` : `Stop sharing “${book.title}”?`,
    message: next === 'shared'
      ? 'Everyone signed in to this instance will be able to read it. Their reading position and notes stay their own, and nothing about your folders is shared.'
      : state.other_readers
        ? `${state.other_readers} other reader(s) have notes on this. They keep them — re-share and their notes come back.`
        : 'Nobody else will be able to open it.',
    confirmLabel: next === 'shared' ? 'Share' : 'Stop sharing',
    danger: next === 'private',
    run: async () => { await sharing.setVisibility(book.id, next) },
  }
}

function bookActions(book: Book) {
  return [
    { label: 'Rename', icon: 'pencil', run: () => renameBook(book) },
    { label: book.visibility === 'shared' ? 'Stop sharing' : 'Share with instance',
      icon: 'inbox', run: () => toggleShare(book) },
    { label: 'Open', icon: 'file', run: () => navigateTo(`/books/${book.id}`) },
    { label: 'Download', icon: 'download',
      run: () => window.open(`/api/library/books/${book.id}/content`, '_blank') },
    { label: 'Move to…', icon: 'folder', run: () => startMove(book, 'book') },
    ...(currentId.value !== null
      ? [{ label: 'Move up one level', icon: 'arrow-up', run: () => moveUp(book, 'book') }]
      : []),
    { label: 'Move to trash', icon: 'trash', danger: true, run: () => deleteBook(book) },
  ]
}

const isEmpty = computed(() => !folders.value.length && !books.value.length)
const bookHref = (book: Book) => `/books/${book.id}`

function itemLabel(folder: Folder): string {
  const count = folder.item_count ?? folder.book_count
  return count === 0 ? 'Empty' : `${count} item${count === 1 ? '' : 's'}`
}
</script>

<template>
  <div class="shell" @dragenter.prevent="onDragEnter" @dragover.prevent
       @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
    <header class="topbar">
      <div class="brand">
        <AppLogo :size="24" />
        <strong>LumaIndex</strong>
      </div>
      <div class="account">
        <ThemeToggle />
        <NuxtLink class="quiet-link" to="/shared">
          <AppIcon name="inbox" :size="16" /> Shared
        </NuxtLink>
        <NuxtLink class="quiet-link" to="/trash">
          <AppIcon name="trash" :size="16" /> Trash
        </NuxtLink>
        <NuxtLink class="quiet-link" to="/settings">
          <AppIcon name="settings" :size="16" /> Settings
        </NuxtLink>
        <span class="who tertiary">{{ user?.display_name || user?.email }}</span>
        <AppButton variant="ghost" size="sm" @click="logout">Sign out</AppButton>
      </div>
    </header>

    <main class="wrap">
      <nav class="crumbs" aria-label="Breadcrumb">
        <button type="button" class="crumb" @click="goTo(null)">My library</button>
        <template v-for="crumb in breadcrumbs" :key="crumb.id">
          <AppIcon name="chevron-right" :size="14" class="sep" />
          <button type="button" class="crumb" @click="goTo(crumb.id)">{{ crumb.name }}</button>
        </template>
        <template v-if="currentFolder">
          <AppIcon name="chevron-right" :size="14" class="sep" />
          <span class="crumb current" aria-current="page">{{ currentFolder.name }}</span>
        </template>
      </nav>

      <div class="toolbar">
        <div class="search">
          <AppIcon name="search" :size="16" />
          <input v-model="search" type="search" placeholder="Search titles…"
                 aria-label="Search titles" />
        </div>
        <div class="spacer" />
        <ViewToggle v-model="view" />
        <AppButton icon="folder-plus" :disabled="busy" @click="newFolder">New folder</AppButton>
        <AppButton variant="primary" icon="upload" :loading="busy"
                   @click="fileInput?.click()">Upload</AppButton>
        <input ref="fileInput" class="sr-only" type="file" multiple tabindex="-1"
               accept="application/pdf,.pdf,.zip,application/zip" @change="onPick" />
      </div>

      <p v-if="error" class="notice notice-error" role="alert">
        <AppIcon name="warning" :size="17" /> {{ error }}
      </p>
      <p v-else-if="notice" class="notice notice-info" role="status">
        <AppIcon name="check" :size="17" /> {{ notice }}
      </p>

      <ul v-if="batches.length" class="batches">
        <li v-for="batch in batches" :key="batch.id" class="panel">
          <AppIcon name="upload" :size="17" />
          <div class="batch-body">
            <strong>{{ batch.original_filename }}</strong>
            <span class="tertiary">
              {{ batch.status === 'pending' ? 'queued' : batch.status }}
              <template v-if="batch.counts.discovered">
                · {{ batch.counts.imported }}/{{ batch.counts.discovered }} imported
              </template>
              <template v-if="batch.counts.skipped_duplicate">
                · {{ batch.counts.skipped_duplicate }} already here
              </template>
            </span>
          </div>
        </li>
      </ul>

      <!-- Skeleton, empty, or content — never two at once ------------- -->
      <div v-if="loading" :class="['cards', view === 'list' ? 'grid' : view]">
        <div v-for="n in 8" :key="n" class="card panel skeleton">
          <div class="skeleton-cover" /><div class="skeleton-line" />
        </div>
      </div>

      <EmptyState v-else-if="isEmpty"
                  :icon="search ? 'search' : 'inbox'"
                  :title="search ? 'Nothing matches that' : 'This folder is empty'"
                  :description="search
                    ? 'Try a different word, or clear the search.'
                    : 'Drag PDFs here, or upload a ZIP — its folders are recreated as you had them.'">
        <AppButton v-if="!search" variant="primary" icon="upload" @click="fileInput?.click()">
          Upload files
        </AppButton>
      </EmptyState>

      <!-- List --------------------------------------------------------- -->
      <div v-else-if="view === 'list'" class="listing panel">
        <div class="row head">
          <span>Name</span><span>Size</span><span>Pages</span><span />
        </div>
        <div v-for="folder in folders" :key="`f${folder.id}`" class="row"
             :class="{ 'drop-into': dropTarget === folder.id }" draggable="true"
             @dragstart="onRowDragStart($event, 'folder', folder.id)" @dragend="onRowDragEnd"
             @dragover="onFolderDragOver($event, folder)"
             @dragleave="dropTarget = 'none'" @drop="onFolderDrop($event, folder)">
          <button class="cell name" type="button" @click="open(folder)">
            <span class="folder-chip"><AppIcon name="folder" :size="17" /></span>
            <span class="label">{{ folder.name }}</span>
          </button>
          <span class="cell tertiary">{{ itemLabel(folder) }}</span>
          <span class="cell" />
          <RowMenu :actions="folderActions(folder)" :label="`Actions for ${folder.name}`" />
        </div>
        <div v-for="book in books" :key="`b${book.id}`" class="row" draggable="true"
             @dragstart="onRowDragStart($event, 'book', book.id)" @dragend="onRowDragEnd">
          <NuxtLink class="cell name" :to="bookHref(book)">
            <BookCover :book="book" size="sm" />
            <span class="label">{{ book.title }}</span>
            <span v-if="book.visibility === 'shared'" class="badge-shared">shared</span>
            <span v-if="book.source?.availability_status !== 'available'" class="badge-warn">
              unavailable
            </span>
          </NuxtLink>
          <span class="cell tertiary">{{ book.source ? formatBytes(book.source.file_size) : '—' }}</span>
          <span class="cell tertiary">{{ book.page_count ?? '…' }}</span>
          <RowMenu :actions="bookActions(book)" :label="`Actions for ${book.title}`" />
        </div>
      </div>

      <!-- Grid and large icons ----------------------------------------- -->
      <div v-else :class="['cards', view]">
        <div v-for="folder in folders" :key="`f${folder.id}`"
             class="card folder-card panel"
             :class="{ 'drop-into': dropTarget === folder.id }" draggable="true"
             @dragstart="onRowDragStart($event, 'folder', folder.id)" @dragend="onRowDragEnd"
             @dragover="onFolderDragOver($event, folder)"
             @dragleave="dropTarget = 'none'" @drop="onFolderDrop($event, folder)">
          <button class="card-open" type="button" @click="open(folder)">
            <span class="folder-art"><AppIcon name="folder" :size="view === 'large' ? 34 : 26" /></span>
            <span class="card-title">{{ folder.name }}</span>
            <span class="card-meta tertiary">{{ itemLabel(folder) }}</span>
          </button>
          <RowMenu class="card-menu" :actions="folderActions(folder)"
                   :label="`Actions for ${folder.name}`" />
        </div>
        <div v-for="book in books" :key="`b${book.id}`" class="card panel" draggable="true"
             @dragstart="onRowDragStart($event, 'book', book.id)" @dragend="onRowDragEnd">
          <NuxtLink class="card-open" :to="bookHref(book)">
            <BookCover :book="book" :size="view === 'large' ? 'lg' : 'md'" />
            <span class="card-title">{{ book.title }}</span>
            <span class="card-meta tertiary">
              {{ book.page_count ? `${book.page_count} pages` : 'Preparing…' }}
              <template v-if="book.source"> · {{ formatBytes(book.source.file_size) }}</template>
            </span>
          </NuxtLink>
          <RowMenu class="card-menu" :actions="bookActions(book)"
                   :label="`Actions for ${book.title}`" />
        </div>
      </div>

    </main>

    <!-- pointer-events: none, or this overlay would intercept every drop that
         was aimed at a folder row underneath it. -->
    <div v-if="dragging && !dragPayload" class="dropzone" aria-hidden="true">
      <div class="dropzone-inner">
        <AppIcon name="upload" :size="26" />
        <strong>Drop to add to {{ currentFolder?.name || 'your library' }}</strong>
        <span class="tertiary">PDFs, or a ZIP of them</span>
      </div>
    </div>

    <FolderPicker v-if="moving" :title="`Move “${moving.name}”`"
                  :exclude-folder-id="moving.kind === 'folder' ? moving.id : null"
                  :current-folder-id="moving.currentFolder"
                  :busy="busy" :error="moveError"
                  @cancel="moving = null" @choose="completeMove" />

    <PromptDialog v-if="dialog" :title="dialog.title" :label="dialog.label"
                  :model-value="dialog.value" :confirm-label="dialog.confirmLabel"
                  :danger="dialog.danger" :message="dialog.message" :busy="busy"
                  @cancel="dialog = null"
                  @confirm="value => act(() => dialog!.run(value))" />
  </div>
</template>

<style scoped>
.shell { min-height: 100dvh; display: flex; flex-direction: column; }

.topbar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 20;
}
.brand { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-md); }
.account { display: flex; align-items: center; gap: var(--space-3); }
.quiet-link {
  display: inline-flex; align-items: center; gap: var(--space-2);
  color: var(--text-secondary); text-decoration: none; font-size: var(--text-base);
}
.quiet-link:hover { color: var(--text); }
.who { font-size: var(--text-sm); }

.wrap { width: 100%; max-width: 72rem; margin: 0 auto;
        padding: var(--space-5); display: grid; gap: var(--space-4); align-content: start; }

.crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); }
.crumb {
  background: none; border: 0; padding: var(--space-1) var(--space-2);
  color: var(--accent-text); font-size: var(--text-base); border-radius: var(--radius-sm);
  cursor: pointer;
}
.crumb:hover { background: var(--surface-hover); }
.crumb.current { color: var(--text); font-weight: 500; cursor: default; }
.sep { color: var(--text-tertiary); }

.toolbar { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }
.search { position: relative; display: flex; align-items: center; width: min(20rem, 100%); }
.search > svg { position: absolute; left: var(--space-3); color: var(--text-tertiary); }
.search input { padding-left: calc(var(--space-3) * 2 + 16px); }
.spacer { flex: 1; }

.batches { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.batches li { display: flex; align-items: center; gap: var(--space-3);
              padding: var(--space-3) var(--space-4); color: var(--text-secondary); }
.batch-body { display: flex; flex-direction: column; }
.batch-body strong { color: var(--text); font-size: var(--text-base); }
.batch-body span { font-size: var(--text-sm); }

/* -- list -------------------------------------------------------------- */
.listing { overflow: hidden; }
.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 8rem 5rem 40px;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}
.row:last-child { border-bottom: 0; }
.row:not(.head):hover { background: var(--surface-hover); }
.row[draggable="true"] { cursor: grab; }
.row.drop-into, .card.drop-into {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  background: var(--accent-soft);
}
.row.head {
  font-size: var(--text-xs); text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-tertiary); background: var(--surface-sunken); padding-block: var(--space-2);
}
.cell { min-width: 0; font-size: var(--text-base); }
.name {
  display: flex; align-items: center; gap: var(--space-3);
  background: none; border: 0; padding: var(--space-1) 0; text-align: left;
  color: var(--text); text-decoration: none; cursor: pointer; min-width: 0;
}
.name:hover .label { color: var(--accent-text); }
.label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.folder-chip {
  display: grid; place-items: center; width: 28px; height: 28px; flex: none;
  border-radius: var(--radius-sm); background: var(--accent-soft); color: var(--accent-text);
}
.badge-shared {
  flex: none; font-size: var(--text-xs); padding: 2px var(--space-2);
  border-radius: var(--radius-full); background: var(--accent-soft); color: var(--accent-text);
}
.badge-warn {
  flex: none; font-size: var(--text-xs); padding: 2px var(--space-2);
  border-radius: var(--radius-full); background: var(--danger-soft); color: var(--danger-text);
}

/* -- cards ------------------------------------------------------------- */
.cards {
  display: grid;
  gap: var(--space-4);
  /* A default, not just a fallback: if a modifier class is ever missing the
     grid would otherwise be one full-width column, and a cover at
     aspect-ratio 1/1.414 would stand taller than the viewport. */
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
}
.cards.grid { grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); }
.cards.large { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
/* Belt and braces: nothing in this grid may grow past a sensible card. */
.cards > .card { max-width: 320px; }
.card { position: relative; padding: var(--space-3); transition: box-shadow var(--duration) var(--ease); }
.card:hover { box-shadow: var(--shadow-md); }
.card-open {
  display: grid; gap: var(--space-2); width: 100%;
  background: none; border: 0; padding: 0; text-align: left;
  color: inherit; text-decoration: none; cursor: pointer;
}
.card-title {
  font-size: var(--text-base); font-weight: 500;
  display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden;
}
.card-meta { font-size: var(--text-xs); }
.card-menu { position: absolute; top: var(--space-2); right: var(--space-2);
             background: var(--surface); border-radius: var(--radius-sm); }
.folder-card .card-open { align-content: start; }
.folder-art {
  display: grid; place-items: center;
  aspect-ratio: 1 / 1.414;
  border-radius: var(--radius-sm);
  background: var(--accent-soft); color: var(--accent-text);
}

/* -- skeleton ----------------------------------------------------------- */
.skeleton { pointer-events: none; }
.skeleton-cover { aspect-ratio: 1 / 1.414; border-radius: var(--radius-sm);
                  background: var(--surface-sunken); }
.skeleton-line { height: 12px; margin-top: var(--space-3); border-radius: var(--radius-full);
                 background: var(--surface-sunken); }

/* -- dropzone ----------------------------------------------------------- */
.dropzone {
  position: fixed; inset: 0; z-index: 40; display: grid; place-items: center;
  padding: var(--space-5); background: rgb(20 19 16 / 45%);
  pointer-events: none;
}
.dropzone-inner {
  display: grid; justify-items: center; gap: var(--space-2);
  padding: var(--space-7) var(--space-6);
  width: min(30rem, 100%);
  border: 2px dashed var(--accent); border-radius: var(--radius-lg);
  background: var(--surface); color: var(--accent-text);
}
.dropzone-inner strong { color: var(--text); }

@media (max-width: 46rem) {
  .row { grid-template-columns: minmax(0, 1fr) 32px; }
  .row > .cell:nth-child(2), .row > .cell:nth-child(3),
  .row.head > span:nth-child(2), .row.head > span:nth-child(3) { display: none; }
  .topbar { padding-inline: var(--space-4); }
  .who { display: none; }
}
</style>
