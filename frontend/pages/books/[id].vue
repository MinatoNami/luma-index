<script setup lang="ts">
import type { FitMode } from '~/composables/usePdf'
import type { Book } from '~/composables/useLibrary'
import type { HighlightColour, Quad } from '~/composables/useAnnotations'

const route = useRoute()
const { api, ensureCsrf } = useApi()
const { settings } = useSettings()

const bookId = computed(() => Number(route.params.id))

const { data } = await useAsyncData(`book-${bookId.value}`, async () => {
  const [book, progress, outline] = await Promise.all([
    api<Book>(`/library/books/${bookId.value}/`),
    api<{ page: number; page_fraction: number }>(`/library/books/${bookId.value}/progress`),
    api<{ items: { title: string; page: number | null; level: number }[] }>(
      `/library/books/${bookId.value}/outline`).catch(() => ({ items: [] })),
  ])
  return { book, progress, outline: outline.items }
})

const book = computed(() => data.value?.book ?? null)
const outline = computed(() => data.value?.outline ?? [])

const reader = ref<{
  goTo: (p: number, f?: number) => void
  next: () => void
  previous: () => void
  search: (term: string) => Promise<void>
  nextMatch: () => void
  previousMatch: () => void
  matchCount: number
  activeMatchIndex: number
  searching: boolean
  doc: import('pdfjs-dist').PDFDocumentProxy | null
} | null>(null)

const thumbnails = ref(false)
const annotationsOpen = ref(false)

const notes = useAnnotations(bookId)
const COLOURS: HighlightColour[] = ['yellow', 'green', 'blue', 'pink']

// The floating toolbar shown over a fresh selection.
const pendingSelection = ref<
  { page: number; quads: Quad[]; text: string; x: number; y: number } | null>(null)
// The highlight whose popover is open — colour, note, remove.
const activeHighlight = ref<{ id: number; x: number; y: number } | null>(null)
// Separately, the note editor dialog.
const editing = ref<{ id: number; note: string } | null>(null)
const noteDraft = ref('')

const activeHighlightRecord = computed(() =>
  notes.highlights.value.find(h => h.id === activeHighlight.value?.id) ?? null)

onMounted(() => notes.loadAll().catch(() => {}))

const scanned = computed(() => book.value?.has_text_layer === false)
const currentBookmark = computed(() =>
  notes.bookmarks.value.find(b => b.page === page.value - 1) ?? null)

async function toggleBookmark() {
  try {
    if (currentBookmark.value) await notes.removeBookmark(currentBookmark.value.id)
    else await notes.addBookmark(page.value - 1)
  } catch { /* a failed bookmark is not worth an interruption */ }
}

async function highlightSelection(colour: HighlightColour) {
  const selection = pendingSelection.value
  if (!selection) return
  pendingSelection.value = null
  window.getSelection()?.removeAllRanges()
  try {
    await notes.addHighlight({
      page: selection.page,
      selected_text: selection.text,
      position_data: { v: 1, quads: selection.quads },
      colour,
    })
  } catch {
    readerError.value = 'That highlight could not be saved.'
  }
}

function openHighlight(payload: { id: number; x: number; y: number }) {
  // Clicking a highlight opens its own controls. Previously it went straight
  // to the note editor, which left no way to change the colour or remove it —
  // so a highlight, once made, was permanent.
  activeHighlight.value = payload
}

function editNote() {
  const highlight = activeHighlightRecord.value
  if (!highlight) return
  editing.value = { id: highlight.id, note: highlight.note }
  noteDraft.value = highlight.note
  activeHighlight.value = null
}

async function recolour(colour: HighlightColour) {
  const highlight = activeHighlightRecord.value
  if (!highlight) return
  await notes.updateHighlight(highlight.id, { colour })
  activeHighlight.value = null
}

async function removeActiveHighlight() {
  const highlight = activeHighlightRecord.value
  if (!highlight) return
  activeHighlight.value = null
  await notes.removeHighlight(highlight.id)
}

async function saveNote() {
  if (!editing.value) return
  await notes.updateHighlight(editing.value.id, { note: noteDraft.value.trim() })
  editing.value = null
}

async function addPageNote() {
  const body = prompt(`Note on page ${page.value}`)
  if (body?.trim()) await notes.addNote(page.value - 1, body.trim())
}

const searchOpen = ref(false)
const searchTerm = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
let searchDebounce: ReturnType<typeof setTimeout> | null = null

// Debounced: a search sweeps every page, and firing that on each keystroke
// would start a full-document pass per character.
watch(searchTerm, (term) => {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => reader.value?.search(term), 350)
})

async function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) {
    await nextTick()
    searchInput.value?.focus()
  } else {
    searchTerm.value = ''
    reader.value?.search('')
  }
}

const mode = ref<'continuous' | 'single'>(settings.value?.reader_mode ?? 'continuous')
const fit = ref<FitMode>(
  settings.value?.reader_zoom === 'fit-page' ? 'fit-page' : 'fit-width',
)
const sidebar = ref(false)
const page = ref((data.value?.progress.page ?? 0) + 1)
const totalPages = ref(data.value?.book.page_count ?? 0)
const jumpTo = ref('')
const readerError = ref('')

const contentUrl = computed(() => `/api/library/books/${bookId.value}/content`)
const percentage = computed(() =>
  totalPages.value ? Math.round((page.value / totalPages.value) * 100) : 0)

// -- progress -------------------------------------------------------------- //

let pending: { page: number; fraction: number } | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null

function onPosition(position: { page: number; fraction: number }) {
  page.value = position.page + 1
  pending = position
  // Debounced: a scroll produces a position on every frame, and §21 asks for
  // throttled writes rather than one per pixel.
  if (saveTimer) return
  saveTimer = setTimeout(() => {
    saveTimer = null
    flush()
  }, 4000)
}

async function flush() {
  if (!pending) return
  const position = pending
  pending = null
  try {
    await ensureCsrf()
    await api(`/library/books/${bookId.value}/progress`, {
      method: 'PUT',
      body: {
        page: position.page,
        page_fraction: position.fraction,
        // Lets the server drop this write if a later position already arrived
        // from another device.
        client_updated_at: new Date().toISOString(),
      },
    })
  } catch {
    // Losing a progress update is not worth interrupting a reader over.
  }
}

// pagehide rather than unload: it is the one that actually fires on mobile
// Safari when a tab is closed or backgrounded.
function onPageHide() {
  if (!pending) return
  const position = pending
  navigator.sendBeacon?.(
    `/api/library/books/${bookId.value}/progress`,
    new Blob([JSON.stringify(position)], { type: 'application/json' }),
  )
}

onMounted(() => {
  window.addEventListener('pagehide', onPageHide)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPageHide)
  window.removeEventListener('keydown', onKey)
  if (saveTimer) clearTimeout(saveTimer)
  flush()
})

// -- navigation ------------------------------------------------------------- //

function onKey(event: KeyboardEvent) {
  if (event.target instanceof HTMLInputElement) return
  if ((event.key === 'f' || event.key === 'F') && (event.metaKey || event.ctrlKey)
      && book.value?.has_text_layer !== false) {
    event.preventDefault()
    toggleSearch()
    return
  }
  if (event.key === 'Escape') {
    if (activeHighlight.value) { activeHighlight.value = null; return }
    if (pendingSelection.value) { pendingSelection.value = null; return }
    if (searchOpen.value) { toggleSearch(); return }
  }

  const actions: Record<string, () => void> = {
    ArrowRight: () => reader.value?.next(),
    PageDown: () => reader.value?.next(),
    ArrowLeft: () => reader.value?.previous(),
    PageUp: () => reader.value?.previous(),
    Home: () => reader.value?.goTo(1),
    End: () => reader.value?.goTo(totalPages.value),
  }
  const action = actions[event.key]
  if (action) {
    event.preventDefault()
    action()
  }
}

function submitJump() {
  const target = Number(jumpTo.value)
  if (Number.isFinite(target) && target >= 1) reader.value?.goTo(target)
  jumpTo.value = ''
}

const { saveSettings } = useSettings()
let prefsTimer: ReturnType<typeof setTimeout> | null = null

// Debounced: toggling fit or mode a few times in a row should not be a request
// each time.
watch([mode, fit], ([nextMode, nextFit]) => {
  if (prefsTimer) clearTimeout(prefsTimer)
  prefsTimer = setTimeout(() => {
    saveSettings({
      reader_mode: nextMode,
      // A numeric zoom is a per-session thing; only the fit modes are worth
      // carrying to another device.
      reader_zoom: typeof nextFit === 'number' ? 'fit-width' : nextFit,
    }).catch(() => {})
  }, 1200)
})

function zoomIn() {
  fit.value = typeof fit.value === 'number' ? Math.min(4, fit.value + 0.2) : 1.2
}
function zoomOut() {
  fit.value = typeof fit.value === 'number' ? Math.max(0.25, fit.value - 0.2) : 0.8
}

async function fullscreen() {
  const shell = document.querySelector('.reader-shell')
  if (!document.fullscreenElement) await shell?.requestFullscreen?.()
  else await document.exitFullscreen()
}

useHead({ title: computed(() => book.value ? `${book.value.title} — LumaIndex` : 'LumaIndex') })
</script>

<template>
  <div class="reader-shell">
    <header class="bar">
      <div class="left">
        <NuxtLink class="back" :to="book?.folder ? `/?folder=${book.folder}` : '/'">
          <AppIcon name="chevron-right" :size="16" class="flip" />
          <span class="sr-only">Back to library</span>
        </NuxtLink>
        <AppButton v-if="outline.length" variant="ghost" size="sm" icon-only icon="list-view"
                   :title="sidebar ? 'Hide contents' : 'Show contents'"
                   @click="sidebar = !sidebar; thumbnails = false" />
        <AppButton variant="ghost" size="sm" icon-only icon="grid-view"
                   :title="thumbnails ? 'Hide page thumbnails' : 'Show page thumbnails'"
                   @click="thumbnails = !thumbnails; sidebar = false" />
        <AppButton variant="ghost" size="sm" icon-only icon="inbox"
                   :title="annotationsOpen ? 'Hide notes' : 'Bookmarks, highlights and notes'"
                   @click="annotationsOpen = !annotationsOpen" />
        <h1>{{ book?.title }}</h1>
      </div>

      <div class="middle">
        <AppButton variant="ghost" size="sm" icon-only icon="arrow-up" title="Previous page"
                   class="flip-up" @click="reader?.previous()" />
        <form class="jump" @submit.prevent="submitJump">
          <input v-model="jumpTo" type="text" inputmode="numeric"
                 :placeholder="String(page)" aria-label="Jump to page" />
          <span class="of">/ {{ totalPages || '…' }}</span>
        </form>
        <AppButton variant="ghost" size="sm" icon-only icon="arrow-up" title="Next page"
                   class="flip-down" @click="reader?.next()" />
        <span class="pct tertiary">{{ percentage }}%</span>
        <AppButton variant="ghost" size="sm" icon-only
                   :icon="currentBookmark ? 'check' : 'file'"
                   :class="{ bookmarked: currentBookmark }"
                   :title="currentBookmark ? 'Remove bookmark' : 'Bookmark this page'"
                   @click="toggleBookmark" />
      </div>

      <div class="right">
        <AppButton v-if="book?.has_text_layer !== false" variant="ghost" size="sm" icon-only
                   icon="search" title="Find in book (⌘F)" @click="toggleSearch" />
        <AppButton variant="ghost" size="sm" :title="'Zoom out'" @click="zoomOut">−</AppButton>
        <AppButton variant="ghost" size="sm"
                   :title="fit === 'fit-width' ? 'Fit page' : 'Fit width'"
                   @click="fit = fit === 'fit-width' ? 'fit-page' : 'fit-width'">
          {{ fit === 'fit-page' ? 'Fit page' : 'Fit width' }}
        </AppButton>
        <AppButton variant="ghost" size="sm" :title="'Zoom in'" @click="zoomIn">+</AppButton>
        <AppButton variant="ghost" size="sm"
                   :title="mode === 'continuous' ? 'Single page' : 'Continuous scroll'"
                   @click="mode = mode === 'continuous' ? 'single' : 'continuous'">
          {{ mode === 'continuous' ? 'Scroll' : 'Page' }}
        </AppButton>
        <AppButton variant="ghost" size="sm" icon-only icon="large-view" title="Fullscreen"
                   @click="fullscreen" />
      </div>
    </header>

    <div v-if="searchOpen" class="findbar">
      <AppIcon name="search" :size="16" />
      <input ref="searchInput" v-model="searchTerm" type="search"
             placeholder="Find in book…" aria-label="Find in book"
             @keydown.enter.prevent="reader?.nextMatch()"
             @keydown.shift.enter.prevent="reader?.previousMatch()" />
      <span class="count tertiary">
        <template v-if="reader?.searching">searching…</template>
        <template v-else-if="!searchTerm">&nbsp;</template>
        <template v-else-if="reader?.matchCount">
          {{ (reader?.activeMatchIndex ?? 0) + 1 }} of {{ reader?.matchCount }}
        </template>
        <template v-else>no matches</template>
      </span>
      <AppButton variant="ghost" size="sm" icon-only icon="arrow-up" title="Previous match"
                 :disabled="!reader?.matchCount" @click="reader?.previousMatch()" />
      <AppButton variant="ghost" size="sm" icon-only icon="arrow-up" class="flip-down"
                 title="Next match" :disabled="!reader?.matchCount"
                 @click="reader?.nextMatch()" />
      <AppButton variant="ghost" size="sm" icon-only icon="close" title="Close"
                 @click="toggleSearch" />
    </div>

    <p v-if="book && book.has_text_layer === false" class="scanned notice notice-info">
      <AppIcon name="warning" :size="16" />
      This looks like a scan, so it has no searchable text.
    </p>

    <div class="body">
      <aside v-if="sidebar && outline.length" class="outline">
        <h2>Contents</h2>
        <ul>
          <li v-for="(item, index) in outline" :key="index"
              :style="{ paddingInlineStart: `${item.level * 12}px` }">
            <button type="button" :disabled="item.page === null"
                    @click="item.page !== null && reader?.goTo(item.page + 1)">
              {{ item.title }}
            </button>
          </li>
        </ul>
      </aside>

      <PageThumbnails v-if="thumbnails" :doc="reader?.doc ?? null"
                      :page-count="totalPages" :current="page"
                      @select="n => reader?.goTo(n)" />

      <div class="stage">
        <ClientOnly>
          <PdfReader ref="reader" :src="contentUrl" :page-count="totalPages"
                     :initial-page="data?.progress.page ?? 0"
                     :initial-fraction="data?.progress.page_fraction ?? 0"
                     :mode="mode" :fit="fit"
                     :highlights="notes.highlights.value"
                     @position="onPosition"
                     @loaded="({ pageCount }) => (totalPages = pageCount)"
                     @error="msg => (readerError = msg)"
                     @select="s => { pendingSelection = s; activeHighlight = null }"
                     @clear-selection="pendingSelection = null"
                     @open-highlight="openHighlight" />
          <template #fallback>
            <div class="stage-loading"><span class="tertiary">Loading the reader…</span></div>
          </template>
        </ClientOnly>
      </div>
      <aside v-if="annotationsOpen" class="notes-panel">
        <header class="panel-head">
          <h2>Notes</h2>
          <AppButton variant="ghost" size="sm" @click="addPageNote">Add page note</AppButton>
        </header>

        <p v-if="!notes.bookmarks.value.length && !notes.highlights.value.length
                 && !notes.notes.value.length" class="tertiary empty-hint">
          {{ scanned
            ? 'This is a scan, so text cannot be highlighted — bookmarks and page notes still work.'
            : 'Select text to highlight it, or bookmark a page.' }}
        </p>

        <section v-if="notes.bookmarks.value.length">
          <h3>Bookmarks</h3>
          <ul>
            <li v-for="mark in notes.bookmarks.value" :key="mark.id">
              <button type="button" @click="reader?.goTo(mark.page + 1)">
                <strong>Page {{ mark.page + 1 }}</strong>
                <span v-if="mark.label" class="tertiary">{{ mark.label }}</span>
              </button>
              <AppButton variant="ghost" size="sm" icon-only icon="close" title="Remove"
                         @click="notes.removeBookmark(mark.id)" />
            </li>
          </ul>
        </section>

        <section v-if="notes.highlights.value.length">
          <h3>Highlights</h3>
          <ul>
            <li v-for="mark in notes.highlights.value" :key="mark.id">
              <button type="button" @click="reader?.goTo(mark.page + 1); openHighlight(mark.id)">
                <span :class="['swatch', mark.colour]" aria-hidden="true" />
                <span class="excerpt">{{ mark.selected_text || `Page ${mark.page + 1}` }}</span>
                <span v-if="mark.note" class="tertiary note-preview">{{ mark.note }}</span>
              </button>
              <AppButton variant="ghost" size="sm" icon-only icon="close" title="Delete"
                         @click="notes.removeHighlight(mark.id)" />
            </li>
          </ul>
        </section>

        <section v-if="notes.notes.value.length">
          <h3>Page notes</h3>
          <ul>
            <li v-for="note in notes.notes.value" :key="note.id">
              <button type="button" @click="reader?.goTo(note.page + 1)">
                <strong>Page {{ note.page + 1 }}</strong>
                <span class="excerpt">{{ note.body }}</span>
              </button>
              <AppButton variant="ghost" size="sm" icon-only icon="close" title="Delete"
                         @click="notes.removeNote(note.id)" />
            </li>
          </ul>
        </section>
      </aside>
    </div>

    <!-- Selection toolbar -->
    <div v-if="pendingSelection && !scanned" class="selection-bar"
         :style="{ left: `${pendingSelection.x}px`, top: `${pendingSelection.y + 12}px` }">
      <button v-for="colour in COLOURS" :key="colour" type="button"
              :class="['swatch', colour]" :title="`Highlight ${colour}`"
              @click="highlightSelection(colour)" />
    </div>

    <!-- Controls for an existing highlight -->
    <div v-if="activeHighlight && activeHighlightRecord" class="highlight-popover"
         :style="{ left: `${activeHighlight.x}px`, top: `${activeHighlight.y + 8}px` }">
      <div class="swatches">
        <button v-for="colour in COLOURS" :key="colour" type="button"
                :class="['swatch', colour, { active: activeHighlightRecord.colour === colour }]"
                :title="`Change to ${colour}`" @click="recolour(colour)" />
      </div>
      <div class="popover-actions">
        <AppButton variant="ghost" size="sm" icon="pencil" @click="editNote">
          {{ activeHighlightRecord.note ? 'Edit note' : 'Add note' }}
        </AppButton>
        <AppButton variant="ghost" size="sm" icon="trash" class="danger-action"
                   @click="removeActiveHighlight">Remove</AppButton>
      </div>
      <p v-if="activeHighlightRecord.note" class="popover-note">
        {{ activeHighlightRecord.note }}
      </p>
    </div>

    <!-- Note editor -->
    <PromptDialog v-if="editing" title="Note" label="Your note" :model-value="noteDraft"
                  confirm-label="Save"
                  @cancel="editing = null"
                  @confirm="value => { noteDraft = value; saveNote() }" />
  </div>
</template>

<style scoped>
.reader-shell { height: 100dvh; display: flex; flex-direction: column; background: var(--bg); }
.bar {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface); border-bottom: 1px solid var(--border);
  flex: none;
}
.left, .middle, .right { display: flex; align-items: center; gap: var(--space-2); }
.left { flex: 1; min-width: 0; }
.right { flex: 1; justify-content: flex-end; }
h1 { font-size: var(--text-base); font-weight: 500; margin: 0;
     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.back { display: grid; place-items: center; width: 32px; height: 32px;
        color: var(--text-secondary); border-radius: var(--radius-sm); }
.back:hover { background: var(--surface-hover); }
.flip { transform: rotate(180deg); }
:deep(.flip-up svg) { transform: rotate(0deg); }
:deep(.flip-down svg) { transform: rotate(180deg); }
.jump { display: flex; align-items: center; gap: var(--space-1); }
.jump input { width: 3.5rem; min-height: 32px; text-align: center; padding: 0 var(--space-1); }
.of { color: var(--text-tertiary); font-size: var(--text-sm); white-space: nowrap; }
.pct { font-size: var(--text-sm); min-width: 3rem; text-align: right; }

.scanned { margin: var(--space-2) var(--space-3) 0; }

.findbar {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface); border-bottom: 1px solid var(--border);
  flex: none;
}
.findbar input { width: min(18rem, 40vw); min-height: 32px; }
.findbar .count { font-size: var(--text-sm); min-width: 6rem; }

.body { flex: 1; min-height: 0; display: flex; }
.outline {
  width: 16rem; flex: none; overflow: auto;
  border-inline-end: 1px solid var(--border); background: var(--surface);
  padding: var(--space-3);
}
.outline h2 { margin: 0 0 var(--space-2); font-size: var(--text-sm);
              text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); }
.outline ul { list-style: none; margin: 0; padding: 0; }
.outline button {
  display: block; width: 100%; text-align: left; background: none; border: 0;
  color: var(--text); padding: var(--space-2); border-radius: var(--radius-sm);
  font-size: var(--text-sm); cursor: pointer;
}
.outline button:hover:not(:disabled) { background: var(--surface-hover); }
.outline button:disabled { color: var(--text-tertiary); cursor: default; }

.stage { flex: 1; min-width: 0; }

.notes-panel {
  width: 19rem; flex: none; overflow: auto; padding: var(--space-3);
  background: var(--surface); border-inline-start: 1px solid var(--border);
}
.panel-head { display: flex; align-items: center; justify-content: space-between;
              margin-bottom: var(--space-3); }
.panel-head h2 { margin: 0; font-size: var(--text-sm); text-transform: uppercase;
                 letter-spacing: 0.04em; color: var(--text-tertiary); }
.notes-panel h3 { margin: var(--space-4) 0 var(--space-2); font-size: var(--text-sm);
                  color: var(--text-secondary); }
.notes-panel ul { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-1); }
.notes-panel li { display: flex; align-items: flex-start; gap: var(--space-1); }
.notes-panel li button:first-child {
  flex: 1; min-width: 0; display: grid; gap: 2px; text-align: left;
  background: none; border: 0; padding: var(--space-2); border-radius: var(--radius-sm);
  color: var(--text); font-size: var(--text-sm); cursor: pointer;
}
.notes-panel li button:first-child:hover { background: var(--surface-hover); }
.excerpt, .note-preview {
  display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; font-size: var(--text-xs);
}
.empty-hint { font-size: var(--text-sm); }

.swatch { width: 14px; height: 14px; border-radius: 4px; border: 1px solid var(--border);
          flex: none; }
.swatch.yellow { background: #FFD64F; }
.swatch.green  { background: #7ED994; }
.swatch.blue   { background: #82B1FF; }
.swatch.pink   { background: #FF9CC4; }

.selection-bar {
  position: fixed; z-index: 60; transform: translateX(-50%);
  display: flex; gap: var(--space-2); padding: var(--space-2);
  background: var(--surface-raised); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-lg);
}
.selection-bar .swatch { width: 22px; height: 22px; cursor: pointer; }

.highlight-popover {
  position: fixed; z-index: 60; transform: translateX(-50%);
  display: grid; gap: var(--space-2); padding: var(--space-2);
  min-width: 13rem; max-width: 18rem;
  background: var(--surface-raised); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-lg);
}
.highlight-popover .swatches { display: flex; gap: var(--space-2); }
.highlight-popover .swatch { width: 22px; height: 22px; cursor: pointer; }
.highlight-popover .swatch.active { box-shadow: 0 0 0 2px var(--accent); }
.popover-actions { display: flex; gap: var(--space-1); }
.popover-note { margin: 0; font-size: var(--text-xs); color: var(--text-secondary);
                border-top: 1px solid var(--border); padding-top: var(--space-2); }
:deep(.danger-action) { color: var(--danger-text); }
:deep(.bookmarked) { color: var(--accent-text); }
.stage-loading { display: grid; place-items: center; height: 100%; }

@media (max-width: 52rem) {
  .right :deep(button:nth-child(-n+3)) { display: none; }
  .outline { position: absolute; z-index: 10; height: calc(100% - 48px);
             box-shadow: var(--shadow-lg); }
}
</style>
