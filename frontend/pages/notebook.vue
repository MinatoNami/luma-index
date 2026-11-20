<script setup lang="ts">
import type { HighlightColour } from '~/composables/useAnnotations'
import type { NotebookEntry } from '~/composables/useNotebook'

/**
 * Everything you have written, across every book.
 *
 * Highlights and notes were reachable only from inside the book they were made
 * in, so finding a passage you remembered marking meant remembering which book
 * it was in first. Kindle's notebook, Apple Books' Notes and Readwise are all
 * this page: one list, newest first, that you can search and narrow, where
 * every entry is a link back to the page it came from.
 *
 * The filters live in the URL, so "everything I marked in this book" is a link
 * the book's own page can give you.
 */
const route = useRoute()
const router = useRouter()
const notebook = useNotebook()

const COLOURS: HighlightColour[] = ['yellow', 'green', 'blue', 'pink']
const KINDS = [
  { value: '', label: 'Everything' },
  { value: 'highlight', label: 'Highlights' },
  { value: 'note', label: 'Page notes' },
] as const
const PAGE = 50

const str = (v: unknown) => (typeof v === 'string' ? v : '')

const q = ref(str(route.query.q))
const kind = ref<'' | 'highlight' | 'note'>(
  (['highlight', 'note'] as const).find(k => k === route.query.kind) ?? '')
const colour = ref<HighlightColour | ''>(COLOURS.find(c => c === route.query.colour) ?? '')
const bookId = computed(() => Number(route.query.book) || null)

const items = ref<NotebookEntry[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')

const filtered = computed(() => Boolean(q.value.trim() || kind.value || colour.value || bookId.value))
// The title of the book being narrowed to, from the entries themselves: there
// is no second request to make for a name that is already on the page.
const bookTitle = ref('')

let generation = 0

async function load() {
  const mine = ++generation
  loading.value = true
  error.value = ''
  try {
    const page = await notebook.list(
      { q: q.value, kind: kind.value, colour: colour.value, book: bookId.value },
      { limit: PAGE },
    )
    // A slow answer to an old query must not overwrite a newer one.
    if (mine !== generation) return
    items.value = page.items
    total.value = page.total
    if (bookId.value && page.items.length) bookTitle.value = page.items[0].book.title
    if (!bookId.value) bookTitle.value = ''
  } catch {
    if (mine === generation) error.value = 'The notebook could not be loaded.'
  } finally {
    if (mine === generation) loading.value = false
  }
}

async function more() {
  loadingMore.value = true
  try {
    const page = await notebook.list(
      { q: q.value, kind: kind.value, colour: colour.value, book: bookId.value },
      { limit: PAGE, offset: items.value.length },
    )
    items.value = [...items.value, ...page.items]
    total.value = page.total
  } catch {
    error.value = 'More could not be loaded.'
  } finally {
    loadingMore.value = false
  }
}

/** Mirror the filters into the URL, so a filtered notebook is a link. */
function syncQuery() {
  const query: Record<string, string> = {}
  if (q.value.trim()) query.q = q.value.trim()
  if (kind.value) query.kind = kind.value
  if (colour.value) query.colour = colour.value
  if (bookId.value) query.book = String(bookId.value)
  router.replace({ query })
}

let typing: ReturnType<typeof setTimeout> | null = null
watch(q, () => {
  if (typing) clearTimeout(typing)
  typing = setTimeout(() => { syncQuery(); load() }, 250)
})
watch([kind, colour], () => { syncQuery(); load() })
watch(bookId, () => load())

// A colour belongs to highlights; choosing one while looking at page notes
// would be a filter that can only ever answer "nothing".
watch(kind, (value) => { if (value === 'note') colour.value = '' })

function toggleColour(value: HighlightColour) {
  colour.value = colour.value === value ? '' : value
  if (colour.value && kind.value === 'note') kind.value = ''
}

function clearBook() {
  const { book: _, ...rest } = route.query
  router.replace({ query: rest })
}

function clearAll() {
  q.value = ''
  kind.value = ''
  colour.value = ''
  router.replace({ query: {} })
}

onMounted(load)
onBeforeUnmount(() => { if (typing) clearTimeout(typing) })

function when(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const sameYear = date.getFullYear() === new Date().getFullYear()
  return date.toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }),
  })
}

const summary = computed(() => {
  if (loading.value) return ''
  const n = total.value
  if (!filtered.value) return n === 1 ? 'One entry' : `${n} entries`
  return n === 1 ? 'One match' : `${n} matches`
})
</script>

<template>
  <main class="wrap">
    <header class="intro">
      <div>
        <h1>Notebook</h1>
        <p class="tertiary">Every highlight and note, from every book.</p>
      </div>
      <!-- The label repeats the visible words, so voice control can still say
           "click Export all" when the phone layout hides them. -->
      <a class="export" :href="notebook.exportUrl(bookId)" download
         :aria-label="bookId ? 'Export this book\'s notes as Markdown'
           : 'Export all notes as Markdown'">
        <AppIcon name="download" :size="16" />
        <span>{{ bookId ? 'Export this book' : 'Export all' }}</span>
      </a>
    </header>

    <div class="toolbar" role="search">
      <div class="search">
        <AppIcon name="search" :size="16" class="search-icon" />
        <label for="notebook-search" class="sr-only">Search your notebook</label>
        <input id="notebook-search" v-model="q" type="search" autocomplete="off"
               placeholder="Search passages, notes and titles…" />
      </div>

      <div class="filters">
        <div class="segmented" role="group" aria-label="Show">
          <button v-for="option in KINDS" :key="option.value" type="button"
                  :aria-pressed="kind === option.value"
                  @click="kind = option.value">{{ option.label }}</button>
        </div>

        <div class="swatches" role="group" aria-label="Highlight colour">
          <button v-for="c in COLOURS" :key="c" type="button" :class="['swatch', c]"
                  :aria-pressed="colour === c" :aria-label="`${c} highlights only`"
                  :title="`${c[0].toUpperCase()}${c.slice(1)} highlights`"
                  @click="toggleColour(c)">
            <AppIcon v-if="colour === c" name="check" :size="14" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="bookId" class="chips">
      <span class="chip">
        In <strong>{{ bookTitle || 'this book' }}</strong>
        <button type="button" class="chip-clear" aria-label="Show every book"
                @click="clearBook">
          <AppIcon name="close" :size="14" />
        </button>
      </span>
      <NuxtLink class="quiet-link" :to="`/books/${bookId}/details`">About this book</NuxtLink>
    </div>

    <p v-if="error" class="notice notice-error" role="alert">
      <AppIcon name="warning" :size="17" /> {{ error }}
    </p>

    <p class="count tertiary" aria-live="polite">{{ summary }}</p>

    <div v-if="loading && !items.length" class="skeletons" aria-hidden="true">
      <div v-for="n in 4" :key="n" class="panel skeleton" />
    </div>

    <EmptyState v-else-if="!items.length && !filtered" icon="notebook"
                title="Nothing written yet"
                description="Select a passage while reading to highlight it. Everything you mark, in every book, collects here." class="panel">
      <NuxtLink class="cta" to="/">Back to reading</NuxtLink>
    </EmptyState>

    <EmptyState v-else-if="!items.length" icon="search" title="Nothing matches"
                description="Try fewer words, or a different colour." class="panel">
      <AppButton @click="clearAll">Clear filters</AppButton>
    </EmptyState>

    <ol v-else class="entries" :aria-busy="loading">
      <li v-for="entry in items" :key="`${entry.kind}-${entry.id}`"
          :class="['entry', 'panel', entry.kind]">
        <span v-if="entry.kind === 'highlight'" :class="['pen', entry.colour]"
              aria-hidden="true" />
        <div class="body">
          <blockquote v-if="entry.kind === 'highlight'" class="passage">
            {{ entry.text || 'A highlighted area with no text under it' }}
          </blockquote>
          <p v-if="entry.kind === 'highlight' && entry.note" class="note">{{ entry.note }}</p>
          <p v-if="entry.kind === 'note'" class="page-note">
            <span class="label">Page note</span>
            {{ entry.text }}
          </p>

          <footer class="meta">
            <NuxtLink class="book" :to="{ path: '/notebook', query: { book: entry.book.id } }">
              {{ entry.book.title }}
            </NuxtLink>
            <NuxtLink class="page" :to="`/books/${entry.book.id}?page=${entry.page + 1}`">
              Page {{ entry.page + 1 }}
              <AppIcon name="chevron-right" :size="13" />
            </NuxtLink>
            <span class="when tertiary">{{ when(entry.created_at) }}</span>
          </footer>
        </div>
      </li>
    </ol>

    <div v-if="items.length < total" class="more">
      <AppButton :loading="loadingMore" @click="more">
        Show more ({{ total - items.length }} left)
      </AppButton>
    </div>
  </main>
</template>

<style scoped>
.wrap {
  flex: 1; width: 100%; max-width: 52rem; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7);
  display: flex; flex-direction: column; gap: var(--space-4);
}

.intro {
  display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4);
}
.intro h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; }
.intro p { margin: var(--space-1) 0 0; font-size: var(--text-base); }

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

/* -- filters -------------------------------------------------------------- */

.toolbar { display: flex; flex-direction: column; gap: var(--space-3); }

.search { position: relative; }
.search-icon {
  position: absolute; left: var(--space-3); top: 50%; transform: translateY(-50%);
  color: var(--text-tertiary); pointer-events: none;
}
.search input { padding-left: calc(var(--space-3) + 24px); }

.filters { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }

.segmented {
  display: inline-flex; padding: 2px; gap: 2px;
  background: var(--surface-sunken); border-radius: var(--radius-sm);
}
.segmented button {
  min-height: 32px; padding: 0 var(--space-3);
  border: 0; border-radius: calc(var(--radius-sm) - 2px);
  background: transparent; color: var(--text-secondary);
  font-size: var(--text-sm); cursor: pointer;
}
.segmented button:hover { color: var(--text); }
.segmented button[aria-pressed="true"] {
  background: var(--surface); color: var(--text); font-weight: 500; box-shadow: var(--shadow-sm);
}

.swatches { display: inline-flex; gap: var(--space-2); }
.swatch {
  display: grid; place-items: center;
  /* 28px of colour inside a 32px target. */
  width: 32px; height: 32px; padding: 0;
  border: 2px solid var(--surface); border-radius: var(--radius-full);
  box-shadow: 0 0 0 1px var(--border);
  color: #1C1B18; cursor: pointer;
}
.swatch[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--text); }
.swatch.yellow { background: var(--hl-yellow); }
.swatch.green { background: var(--hl-green); }
.swatch.blue { background: var(--hl-blue); }
.swatch.pink { background: var(--hl-pink); }

.chips { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
.chip {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: 32px; padding: 0 var(--space-1) 0 var(--space-3);
  background: var(--accent-soft); color: var(--accent-text);
  border-radius: var(--radius-full); font-size: var(--text-sm);
}
.chip strong { font-weight: 600; max-width: 22rem;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-clear {
  display: grid; place-items: center; width: 24px; height: 24px; padding: 0;
  border: 0; border-radius: var(--radius-full);
  background: transparent; color: inherit; cursor: pointer;
}
.chip-clear:hover { background: color-mix(in srgb, var(--accent) 15%, transparent); }

.count { margin: 0; min-height: 1.4em; font-size: var(--text-sm); }

/* -- entries -------------------------------------------------------------- */

.entries { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-3); }

.entry {
  position: relative; display: flex; overflow: hidden;
  padding: var(--space-4) var(--space-4) var(--space-3) var(--space-5);
}
/* The pen the passage was marked with, down the edge — the colour carries
   identity, and the text beside it stays in text colours. */
.pen { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.pen.yellow { background: var(--hl-yellow); }
.pen.green { background: var(--hl-green); }
.pen.blue { background: var(--hl-blue); }
.pen.pink { background: var(--hl-pink); }
.entry.note { padding-left: var(--space-4); }

.body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: var(--space-2); }

.passage {
  margin: 0; font-size: var(--text-md); line-height: 1.6; color: var(--text);
  white-space: pre-line; overflow-wrap: anywhere;
}
.note {
  margin: 0; padding-left: var(--space-3);
  border-left: 2px solid var(--border);
  color: var(--text-secondary); font-size: var(--text-base);
  white-space: pre-line; overflow-wrap: anywhere;
}
.page-note { margin: 0; white-space: pre-line; overflow-wrap: anywhere; }
.page-note .label {
  display: block; margin-bottom: var(--space-1);
  font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}

.meta {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3);
  margin-top: var(--space-1); font-size: var(--text-sm);
}
.meta a {
  display: inline-flex; align-items: center; gap: 2px; min-height: 28px;
  text-decoration: none;
}
.book {
  color: var(--text-secondary); font-weight: 500; min-width: 0;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.book:hover { color: var(--text); text-decoration: underline; }
.page { color: var(--accent-text); }
.when { margin-left: auto; font-size: var(--text-xs); }

.more { display: flex; justify-content: center; padding-top: var(--space-2); }

.skeletons { display: grid; gap: var(--space-3); }
.skeleton { height: 112px; background: var(--surface-sunken); border-color: transparent; }

@media (max-width: 40rem) {
  .wrap { padding: var(--space-5) var(--space-4) var(--space-6); gap: var(--space-3); }
  .intro { align-items: flex-start; }
  .export span { display: none; }
  .export { width: var(--tap-target); padding: 0; justify-content: center; }
  .when { margin-left: 0; }
}
</style>
