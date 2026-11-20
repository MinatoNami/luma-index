<script setup lang="ts">
import type { HighlightColour } from '~/composables/useAnnotations'
import {
  countLabel, defaultOrder, type NotebookBook, type NotebookEntry, type NotebookOrder,
} from '~/composables/useNotebook'

/**
 * Everything you have written, across every book.
 *
 * Highlights and notes were reachable only from inside the book they were made
 * in, so finding a passage you remembered marking meant remembering which book
 * it was in first. Kindle's notebook, Apple Books' Notes and Readwise are all
 * this page: one list you can search and narrow, where every entry opens the
 * page it came from.
 *
 * Two ways in, because there are two questions. "What did I mark recently?"
 * is the list, newest first. "What did I mark in this book?" is the book list
 * down the side — which is also what makes that filter findable at all — and a
 * book reads in page order, the way you would meet the passages reading it.
 *
 * The filters live in the URL, so a filtered notebook is a link.
 */
const route = useRoute()
const router = useRouter()
const notebook = useNotebook()

const COLOURS: HighlightColour[] = ['yellow', 'green', 'blue', 'pink']
const PAGE = 50

const str = (v: unknown) => (typeof v === 'string' ? v : '')

const q = ref(str(route.query.q))
const kind = ref<'' | 'highlight' | 'note'>(
  (['highlight', 'note'] as const).find(k => k === route.query.kind) ?? '')
const colour = ref<HighlightColour | ''>(COLOURS.find(c => c === route.query.colour) ?? '')
const bookId = computed(() => Number(route.query.book) || null)
const order = computed<NotebookOrder>(() =>
  route.query.order === 'page' || route.query.order === 'recent'
    ? route.query.order : defaultOrder(bookId.value))

const items = ref<NotebookEntry[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')

const shelf = ref<NotebookBook[]>([])
const totals = ref({ highlights: 0, notes: 0 })
const shelfLoaded = ref(false)

const selectedBook = computed(() => shelf.value.find(b => b.id === bookId.value) ?? null)
const empty = computed(() => shelfLoaded.value && !totals.value.highlights && !totals.value.notes)
const searching = computed(() => Boolean(q.value.trim() || colour.value))

// What the kind filter can honestly count: the whole notebook or one book's,
// but only while nothing narrower is in force — "Highlights 9" beside a search
// that matched two would be a number about something else.
const kindCounts = computed(() => {
  if (searching.value) return null
  const source = selectedBook.value ?? (bookId.value ? null : totals.value)
  if (!source) return null
  return { '': source.highlights + source.notes, highlight: source.highlights,
           note: source.notes } as Record<string, number>
})

const KINDS = [
  { value: '', label: 'All' },
  { value: 'highlight', label: 'Highlights' },
  { value: 'note', label: 'Page notes' },
] as const

let generation = 0

function filters() {
  return { q: q.value, kind: kind.value, colour: colour.value, book: bookId.value,
           order: order.value }
}

async function load() {
  const mine = ++generation
  loading.value = true
  error.value = ''
  try {
    const page = await notebook.list(filters(), { limit: PAGE })
    // A slow answer to an old query must not overwrite a newer one.
    if (mine !== generation) return
    items.value = page.items
    total.value = page.total
  } catch {
    if (mine === generation) error.value = 'The notebook could not be loaded.'
  } finally {
    if (mine === generation) loading.value = false
  }
}

async function loadShelf() {
  try {
    const body = await notebook.books()
    shelf.value = body.results
    totals.value = body.totals
  } catch {
    // The list down the side is a convenience; the notebook works without it.
  } finally {
    shelfLoaded.value = true
  }
}

async function more() {
  loadingMore.value = true
  try {
    const page = await notebook.list(filters(), { limit: PAGE, offset: items.value.length })
    items.value = [...items.value, ...page.items]
    total.value = page.total
  } catch {
    error.value = 'More could not be loaded.'
  } finally {
    loadingMore.value = false
  }
}

/** Every filter in the URL — book and order included, so neither is lost. */
function syncQuery(changes: Record<string, string | null> = {}) {
  const next: Record<string, string> = {}
  if (q.value.trim()) next.q = q.value.trim()
  if (kind.value) next.kind = kind.value
  if (colour.value) next.colour = colour.value
  const book = 'book' in changes ? changes.book : (bookId.value ? String(bookId.value) : null)
  if (book) next.book = book
  // Only an order that differs from what that view would choose anyway.
  const wanted = ('order' in changes ? changes.order : str(route.query.order)) || null
  if (wanted && wanted !== defaultOrder(book ? Number(book) : null)) next.order = wanted
  router.replace({ query: next })
}

function chooseBook(id: number | null) {
  // A book has its own natural order; carrying "newest first" over from the
  // whole-notebook view would be a choice nobody made for this book.
  syncQuery({ book: id ? String(id) : null, order: null })
}

function setOrder(value: NotebookOrder) {
  syncQuery({ order: value })
}

let typing: ReturnType<typeof setTimeout> | null = null
watch(q, () => {
  if (typing) clearTimeout(typing)
  typing = setTimeout(() => { syncQuery(); load() }, 250)
})
watch([kind, colour], () => { syncQuery(); load() })
watch([bookId, order], () => load())

// A colour belongs to highlights; choosing one while looking at page notes
// would be a filter that can only ever answer "nothing".
watch(kind, (value) => { if (value === 'note') colour.value = '' })

function toggleColour(value: HighlightColour) {
  colour.value = colour.value === value ? '' : value
  if (colour.value && kind.value === 'note') kind.value = ''
}

function clearAll() {
  q.value = ''
  kind.value = ''
  colour.value = ''
  router.replace({ query: bookId.value ? { book: String(bookId.value) } : {} })
}

onMounted(() => { load(); loadShelf() })
onBeforeUnmount(() => { if (typing) clearTimeout(typing) })

// -- changing entries ------------------------------------------------------- //

function onSaved(updated: NotebookEntry) {
  items.value = items.value.map(e =>
    e.kind === updated.kind && e.id === updated.id ? updated : e)
}

const confirming = ref<NotebookEntry | null>(null)
const deleting = ref(false)

async function confirmRemove() {
  const entry = confirming.value
  if (!entry) return
  deleting.value = true
  try {
    await notebook.remove(entry)
    items.value = items.value.filter(e => !(e.kind === entry.kind && e.id === entry.id))
    total.value = Math.max(0, total.value - 1)
    confirming.value = null
    loadShelf()
  } catch {
    error.value = 'That could not be deleted.'
    confirming.value = null
  } finally {
    deleting.value = false
  }
}

const summary = computed(() => {
  if (loading.value) return 'Loading…'
  const n = total.value
  const filtered = searching.value || kind.value
  if (!filtered) return n === 1 ? 'One entry' : `${n} entries`
  return n === 1 ? 'One match' : `${n} matches`
})

const scope = computed(() => selectedBook.value?.title ?? '')
</script>

<template>
  <main class="wrap">
    <header class="intro">
      <div class="heading">
        <h1>Notebook</h1>
        <p v-if="bookId" class="scope">
          <span class="scope-title">{{ scope || 'One book' }}</span>
          <NuxtLink class="quiet-link" :to="`/books/${bookId}`">Open book</NuxtLink>
          <NuxtLink class="quiet-link" :to="`/books/${bookId}/details`">About</NuxtLink>
        </p>
        <p v-else class="scope tertiary">Every highlight and note, from every book.</p>
      </div>
      <!-- The label repeats the visible words, so voice control can still say
           "click Export" when the phone layout hides them. -->
      <a class="export" :href="notebook.exportUrl(bookId)" download
         :aria-label="bookId ? 'Export this book\'s notes as Markdown'
           : 'Export all notes as Markdown'">
        <AppIcon name="download" :size="16" />
        <span>Export</span>
      </a>
    </header>

    <EmptyState v-if="empty" icon="notebook" title="Nothing written yet" class="panel"
                description="Select a passage while reading to highlight it. Everything you mark, in every book, collects here — searchable, and a click from the page it came from.">
      <NuxtLink class="cta" to="/">Back to reading</NuxtLink>
    </EmptyState>

    <div v-else class="layout">
      <!-- Wide screens: the books, so "only this one" is a click rather than
           something you find by following a title inside an entry. -->
      <nav class="shelf" aria-label="Books in your notebook">
        <p class="label">Books</p>
        <ul>
          <li>
            <button type="button" class="shelf-item" :aria-current="!bookId ? 'true' : undefined"
                    @click="chooseBook(null)">
              <span class="shelf-title">All books</span>
              <span class="shelf-count">{{ totals.highlights + totals.notes }}</span>
            </button>
          </li>
          <li v-for="b in shelf" :key="b.id">
            <button type="button" class="shelf-item"
                    :aria-current="bookId === b.id ? 'true' : undefined"
                    :title="`${b.title} — ${countLabel(b.highlights, b.notes)}`"
                    @click="chooseBook(b.id)">
              <span class="shelf-title">{{ b.title }}</span>
              <span class="shelf-count">{{ b.highlights + b.notes }}</span>
            </button>
          </li>
        </ul>
      </nav>

      <section class="main" aria-label="Entries">
        <div class="toolbar" role="search">
          <div class="search">
            <AppIcon name="search" :size="16" class="search-icon" />
            <label for="notebook-search" class="sr-only">Search your notebook</label>
            <input id="notebook-search" v-model="q" type="search" autocomplete="off"
                   :placeholder="bookId ? 'Search this book’s notes…'
                     : 'Search passages, notes and titles…'" />
          </div>

          <!-- Narrow screens: the same books, as a select. -->
          <div class="book-select">
            <label for="notebook-book" class="sr-only">Book</label>
            <select id="notebook-book" :value="bookId ?? ''"
                    @change="chooseBook(Number(($event.target as HTMLSelectElement).value) || null)">
              <option value="">All books ({{ totals.highlights + totals.notes }})</option>
              <option v-for="b in shelf" :key="b.id" :value="b.id">
                {{ b.title }} ({{ b.highlights + b.notes }})
              </option>
            </select>
          </div>

          <div class="filters">
            <div class="segmented" role="group" aria-label="Show">
              <button v-for="option in KINDS" :key="option.value" type="button"
                      :aria-pressed="kind === option.value" @click="kind = option.value">
                {{ option.label }}
                <span v-if="kindCounts" class="count">{{ kindCounts[option.value] }}</span>
              </button>
            </div>

            <div class="swatches" role="group" aria-label="Highlight colour">
              <span class="swatch-label" aria-hidden="true">Colour</span>
              <button v-for="c in COLOURS" :key="c" type="button" :class="['swatch', c]"
                      :aria-pressed="colour === c" :aria-label="`Only ${c} highlights`"
                      :title="`Only ${c} highlights`" @click="toggleColour(c)">
                <AppIcon v-if="colour === c" name="check" :size="14" />
              </button>
            </div>
          </div>
        </div>

        <div class="results-bar">
          <p class="summary" aria-live="polite">{{ summary }}</p>
          <div class="segmented small" role="group" aria-label="Order">
            <button type="button" :aria-pressed="order === 'recent'"
                    @click="setOrder('recent')">Newest</button>
            <button type="button" :aria-pressed="order === 'page'"
                    @click="setOrder('page')">Page order</button>
          </div>
        </div>

        <p v-if="error" class="notice notice-error" role="alert">
          <AppIcon name="warning" :size="17" /> {{ error }}
        </p>

        <div v-if="loading && !items.length" class="skeletons" aria-hidden="true">
          <div v-for="n in 4" :key="n" class="panel skeleton" />
        </div>

        <EmptyState v-else-if="!items.length" icon="search" title="Nothing matches"
                    description="Try fewer words, another colour, or every book." class="panel">
          <AppButton @click="clearAll">Clear filters</AppButton>
        </EmptyState>

        <ol v-else class="entries" :aria-busy="loading">
          <li v-for="entry in items" :key="`${entry.kind}-${entry.id}`">
            <NotebookEntryCard :entry="entry" :show-book="!bookId"
                               @saved="onSaved" @remove="confirming = $event"
                               @book="chooseBook" />
          </li>
        </ol>

        <div v-if="items.length < total" class="more">
          <AppButton :loading="loadingMore" @click="more">
            Show more ({{ total - items.length }} left)
          </AppButton>
        </div>
      </section>
    </div>

    <PromptDialog v-if="confirming"
                  :title="confirming.kind === 'highlight' ? 'Delete this highlight?' : 'Delete this page note?'"
                  :message="`It disappears from ${confirming.book.title} too. This can’t be undone.`"
                  confirm-label="Delete" danger :busy="deleting"
                  @confirm="confirmRemove" @cancel="confirming = null" />
  </main>
</template>

<style scoped>
.wrap {
  flex: 1; width: 100%; max-width: 70rem; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7);
  display: flex; flex-direction: column; gap: var(--space-5);
}

.intro {
  display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4);
}
.intro h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; }
.scope {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-1) var(--space-3);
  margin: var(--space-1) 0 0; font-size: var(--text-base);
}
.scope-title { font-weight: 500; color: var(--text); }
.scope .quiet-link { display: inline-flex; align-items: center; font-size: var(--text-sm); }

.export, .cta {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: var(--tap-target); padding: 0 var(--space-4);
  border-radius: var(--radius-sm);
  font-size: var(--text-base); font-weight: 500; text-decoration: none; white-space: nowrap;
}
.export {
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); box-shadow: var(--shadow-sm);
}
.export:hover { background: var(--surface-hover); color: var(--text); }
.cta { background: var(--accent); color: var(--on-accent); }
.cta:hover { background: var(--accent-hover); color: var(--on-accent); }

/* -- layout --------------------------------------------------------------- */

.layout {
  display: grid; grid-template-columns: 15rem minmax(0, 1fr); gap: var(--space-6);
  align-items: start;
}
.main { min-width: 0; display: flex; flex-direction: column; gap: var(--space-3); }

/* -- the books ------------------------------------------------------------ */

.shelf {
  position: sticky; top: var(--space-5);
  max-height: calc(100dvh - 2 * var(--space-5)); overflow-y: auto;
}
.label {
  margin: 0 0 var(--space-2); padding: 0 var(--space-3);
  font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}
.shelf ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.shelf-item {
  display: flex; align-items: center; gap: var(--space-2); width: 100%;
  min-height: 36px; padding: var(--space-1) var(--space-3);
  background: none; border: 0; border-radius: var(--radius-sm);
  color: var(--text-secondary); font-size: var(--text-sm); text-align: left; cursor: pointer;
}
.shelf-item:hover { background: var(--surface-hover); color: var(--text); }
.shelf-item[aria-current="true"] { background: var(--accent-soft); color: var(--accent-text); font-weight: 500; }
.shelf-title {
  flex: 1; min-width: 0; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.shelf-count { flex: none; font-size: var(--text-xs); color: var(--text-tertiary);
               font-variant-numeric: tabular-nums; }
.shelf-item[aria-current="true"] .shelf-count { color: var(--accent-text); }

/* -- filters -------------------------------------------------------------- */

.toolbar { display: flex; flex-direction: column; gap: var(--space-3); }

.search { position: relative; }
.search-icon {
  position: absolute; left: var(--space-3); top: 50%; transform: translateY(-50%);
  color: var(--text-tertiary); pointer-events: none;
}
.search input { padding-left: calc(var(--space-3) + 24px); }

.book-select { display: none; }
.book-select select {
  width: 100%; min-height: var(--tap-target); padding: 0 var(--space-3);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
}

.filters {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: var(--space-3);
}

.segmented {
  display: inline-flex; padding: 2px; gap: 2px;
  background: var(--surface-sunken); border-radius: var(--radius-sm);
}
.segmented button {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: 32px; padding: 0 var(--space-3);
  border: 0; border-radius: calc(var(--radius-sm) - 2px);
  background: transparent; color: var(--text-secondary);
  font-size: var(--text-sm); cursor: pointer;
}
.segmented button:hover { color: var(--text); }
.segmented button[aria-pressed="true"] {
  background: var(--surface); color: var(--text); font-weight: 500; box-shadow: var(--shadow-sm);
}
.segmented .count {
  font-size: var(--text-xs); font-weight: 400; color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.segmented.small button { min-height: 28px; padding: 0 var(--space-2); font-size: var(--text-xs); }

.swatches { display: inline-flex; align-items: center; gap: var(--space-2); }
.swatch-label { font-size: var(--text-xs); color: var(--text-tertiary); margin-right: var(--space-1); }
.swatch {
  display: grid; place-items: center;
  width: 28px; height: 28px; padding: 0;
  border: 2px solid var(--surface); border-radius: var(--radius-full);
  box-shadow: 0 0 0 1px var(--border);
  color: #1C1B18; cursor: pointer;
}
.swatch[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--text); }
.swatch.yellow { background: var(--hl-yellow); }
.swatch.green { background: var(--hl-green); }
.swatch.blue { background: var(--hl-blue); }
.swatch.pink { background: var(--hl-pink); }

.results-bar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding-top: var(--space-1);
}
.summary { margin: 0; font-size: var(--text-sm); color: var(--text-tertiary); }

/* -- entries -------------------------------------------------------------- */

.entries { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-3); }

.more { display: flex; justify-content: center; padding-top: var(--space-2); }

.skeletons { display: grid; gap: var(--space-3); }
.skeleton { height: 112px; background: var(--surface-sunken); border-color: transparent; }

@media (max-width: 64rem) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .shelf { display: none; }
  .book-select { display: block; }
}

@media (max-width: 40rem) {
  .wrap { padding: var(--space-5) var(--space-4) var(--space-6); gap: var(--space-4); }
  .intro { align-items: flex-start; }
  .export span { display: none; }
  .export { width: var(--tap-target); padding: 0; justify-content: center; }
  .swatch-label { display: none; }
}
</style>
