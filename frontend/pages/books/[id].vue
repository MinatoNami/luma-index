<script setup lang="ts">
import type { FitMode } from '~/composables/usePdf'
import type { Book } from '~/composables/useLibrary'

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

const reader = ref<{ goTo: (p: number, f?: number) => void; next: () => void
                     previous: () => void } | null>(null)

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
                   @click="sidebar = !sidebar" />
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
      </div>

      <div class="right">
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

      <div class="stage">
        <ClientOnly>
          <PdfReader ref="reader" :src="contentUrl" :page-count="totalPages"
                     :initial-page="data?.progress.page ?? 0"
                     :initial-fraction="data?.progress.page_fraction ?? 0"
                     :mode="mode" :fit="fit"
                     @position="onPosition"
                     @loaded="({ pageCount }) => (totalPages = pageCount)"
                     @error="msg => (readerError = msg)" />
          <template #fallback>
            <div class="stage-loading"><span class="tertiary">Loading the reader…</span></div>
          </template>
        </ClientOnly>
      </div>
    </div>
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
.stage-loading { display: grid; place-items: center; height: 100%; }

@media (max-width: 52rem) {
  .right :deep(button:nth-child(-n+3)) { display: none; }
  .outline { position: absolute; z-index: 10; height: calc(100% - 48px);
             box-shadow: var(--shadow-lg); }
}
</style>
