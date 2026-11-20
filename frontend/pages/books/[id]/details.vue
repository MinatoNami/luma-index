<script setup lang="ts">
import { formatBytes } from '~/composables/useLibrary'
import type { NotebookEntry } from '~/composables/useNotebook'

/**
 * One book, on a page of its own.
 *
 * The app had nowhere to look at a book without reading it: /books/{id} opened
 * the reader, and everything else about a book — where it came from, who can
 * see it, what you have written on it — was spread across a row menu, a picker
 * dialog and the reader's sidebar.
 *
 * Reading stays the fast path. This is reached from a row menu or from the
 * reader, never in front of opening a book.
 */
const route = useRoute()
const library = useLibrary()
const notebook = useNotebook()

const bookId = computed(() => Number(route.params.id))

const { data: book, error } = await useAsyncData(
  () => `book-detail-${bookId.value}`,
  () => library.book(bookId.value),
  { watch: [bookId] },
)

const percent = computed(() => Math.round(book.value?.progress?.percentage ?? 0))
const started = computed(() => Boolean(book.value?.progress))

const folderName = computed(() => {
  const path = book.value?.path
  if (!path) return null
  const parts = path.split('/')
  return parts.length > 1 ? parts[parts.length - 2] : null
})

function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
}

const annotationTotal = computed(() => {
  const a = book.value?.annotations
  return a ? a.bookmarks + a.highlights + a.notes : 0
})

const tally = computed(() => {
  const a = book.value?.annotations
  if (!a) return ''
  const parts: string[] = []
  const say = (n: number, one: string, many: string) => {
    if (n) parts.push(`${n} ${n === 1 ? one : many}`)
  }
  say(a.highlights, 'highlight', 'highlights')
  say(a.notes, 'page note', 'page notes')
  say(a.bookmarks, 'bookmark', 'bookmarks')
  return parts.join(' · ')
})

// The latest few, fetched in the browser: the page is useful without them, and
// a book with hundreds of highlights should not hold up its own details.
const latest = ref<NotebookEntry[]>([])
const PREVIEW = 3
async function loadLatest() {
  latest.value = []
  if (!book.value?.annotations.highlights && !book.value?.annotations.notes) return
  try {
    latest.value = (await notebook.list({ book: bookId.value, order: 'recent' },
                                        { limit: PREVIEW })).items
  } catch {
    latest.value = []
  }
}
onMounted(loadLatest)
watch(bookId, loadLatest)

const moreLabel = computed(() => {
  const n = (book.value?.annotations.highlights ?? 0) + (book.value?.annotations.notes ?? 0)
  return n > latest.value.length ? `See all ${n} in the notebook` : 'Open in the notebook'
})
</script>

<template>
  <main class="wrap">
    <p v-if="error" class="notice notice-error" role="alert">
      <AppIcon name="warning" :size="17" />
      This book could not be loaded.
    </p>

    <template v-else-if="book">
      <nav class="crumbs" aria-label="Breadcrumb">
        <NuxtLink class="quiet-link" to="/library">Library</NuxtLink>
        <template v-if="folderName">
          <AppIcon name="chevron-right" :size="14" />
          <NuxtLink class="quiet-link" :to="`/library?folder=${book.folder}`">
            {{ folderName }}
          </NuxtLink>
        </template>
      </nav>

      <div class="columns">
        <div class="side">
          <BookCover :book="book" size="lg" class="hero" />

          <NuxtLink class="cta" :to="`/books/${book.id}`">
            <AppIcon name="chevron-right" :size="16" />
            {{ started ? `Resume on page ${(book.progress?.page ?? 0) + 1}` : 'Start reading' }}
          </NuxtLink>
        </div>

        <div class="detail">
          <h1>{{ book.title }}</h1>

          <section v-if="started" class="panel progress-card" aria-label="Reading progress">
            <div class="progress-row">
              <span>
                Page {{ (book.progress?.page ?? 0) + 1 }}<template v-if="book.page_count">
                  of {{ book.page_count }}</template>
              </span>
              <strong>{{ percent }}%</strong>
            </div>
            <div class="meter"><div class="fill" :style="{ width: `${percent}%` }" /></div>
          </section>

          <!-- Sharing is a state you should be able to read at a glance, and
               the sentence says what it actually means rather than "shared". -->
          <section v-if="book.visibility === 'shared'" class="panel shared" aria-label="Sharing">
            <AppIcon name="inbox" :size="18" />
            <div>
              <strong>Shared with everyone signed in</strong>
              <p>They keep their own place and their own notes. Yours stay private.</p>
            </div>
          </section>

          <section aria-labelledby="details-heading">
            <h2 id="details-heading">Details</h2>
            <dl class="facts">
              <div><dt>Pages</dt><dd>{{ book.page_count ?? '—' }}</dd></div>
              <div>
                <dt>Size</dt>
                <dd>{{ book.source ? formatBytes(book.source.file_size) : '—' }}</dd>
              </div>
              <div>
                <dt>Text layer</dt>
                <dd>
                  <span v-if="book.has_text_layer === null">—</span>
                  <span v-else-if="book.has_text_layer" class="yes">Searchable</span>
                  <span v-else>Scanned, no text</span>
                </dd>
              </div>
              <div><dt>Added</dt><dd>{{ when(book.created_at) }}</dd></div>
              <div v-if="folderName">
                <dt>Folder</dt>
                <dd><NuxtLink :to="`/library?folder=${book.folder}`">{{ folderName }}</NuxtLink></dd>
              </div>
              <div v-if="book.source">
                <dt>Original file</dt>
                <dd class="filename">{{ book.source.original_filename }}</dd>
              </div>
            </dl>
          </section>

          <section v-if="book.collections.length" aria-labelledby="collections-heading">
            <h2 id="collections-heading">In collections</h2>
            <ul class="tags">
              <li v-for="c in book.collections" :key="c.id">
                <NuxtLink class="tag" :to="`/library?collection=${c.id}`">{{ c.name }}</NuxtLink>
              </li>
            </ul>
          </section>

          <!-- What you wrote, not how much: three counts in tiles looked like
               buttons and went nowhere. The latest few, each a way back to its
               page, and the rest a click away in the notebook. -->
          <section aria-labelledby="notes-heading">
            <div class="section-head">
              <h2 id="notes-heading">Your notes</h2>
              <span v-if="annotationTotal" class="tally">{{ tally }}</span>
            </div>

            <ol v-if="latest.length" class="latest">
              <li v-for="entry in latest" :key="`${entry.kind}-${entry.id}`"
                  :class="['latest-item', `pen-${entry.colour || 'none'}`]">
                <p v-if="entry.kind === 'highlight'" class="latest-passage">{{ entry.text }}</p>
                <p v-else class="latest-note">
                  <span class="latest-kind">Page note</span>{{ entry.text }}
                </p>
                <p v-if="entry.kind === 'highlight' && entry.note" class="latest-own">{{ entry.note }}</p>
                <NuxtLink class="latest-page" :to="`/books/${book.id}?page=${entry.page + 1}`">
                  Page {{ entry.page + 1 }}
                </NuxtLink>
              </li>
            </ol>

            <div v-if="annotationTotal" class="note-actions">
              <NuxtLink v-if="book.annotations.highlights + book.annotations.notes"
                        class="action" :to="`/notebook?book=${book.id}`">
                <AppIcon name="notebook" :size="16" />
                {{ moreLabel }}
              </NuxtLink>
              <!-- Markdown, because it is what Obsidian, Logseq and a plain
                   editor all take without a plugin. -->
              <a class="action quiet" :href="notebook.exportUrl(book.id)" download>
                <AppIcon name="download" :size="16" /> Export as Markdown
              </a>
            </div>
            <p v-else class="tertiary">
              Nothing yet. Select text while reading to highlight it, or bookmark a page.
            </p>
          </section>
        </div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.wrap {
  flex: 1; width: 100%; max-width: 62rem; margin: 0 auto;
  padding: var(--space-5) var(--space-5) var(--space-7);
}

.crumbs {
  display: flex; align-items: center; gap: var(--space-2);
  margin-bottom: var(--space-5); color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.columns { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: var(--space-6); }

.side { display: flex; flex-direction: column; gap: var(--space-4); }
.hero { box-shadow: var(--shadow-lg); }

.cta {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
  min-height: var(--tap-target); padding: 0 var(--space-4);
  background: var(--accent); color: var(--on-accent);
  border-radius: var(--radius-sm);
  font-size: var(--text-base); font-weight: 500; text-decoration: none;
}
.cta:hover { background: var(--accent-hover); color: var(--on-accent); }

.detail { display: flex; flex-direction: column; gap: var(--space-5); }
.detail h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; line-height: 1.25; }
.detail h2 {
  margin: 0 0 var(--space-3); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-tertiary);
}

.progress-card { padding: var(--space-4); }
.progress-row {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: var(--space-3); margin-bottom: var(--space-3);
  font-size: var(--text-sm); color: var(--text-secondary);
}
.progress-row strong { color: var(--accent-text); }
.meter {
  height: 6px; border-radius: var(--radius-full);
  background: var(--surface-sunken); overflow: hidden;
}
.fill { height: 100%; background: var(--accent); border-radius: var(--radius-full); }

.shared {
  display: flex; gap: var(--space-3); padding: var(--space-4);
  background: var(--accent-soft); border-color: var(--accent); color: var(--accent-text);
}
.shared strong { font-size: var(--text-base); }
.shared p { margin: var(--space-1) 0 0; font-size: var(--text-sm); color: var(--text-secondary); }

.facts { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
         gap: 0 var(--space-6); }
.facts > div {
  display: flex; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) 0; border-bottom: 1px solid var(--border);
  font-size: var(--text-base);
}
.facts dt { color: var(--text-secondary); }
.facts dd { margin: 0; text-align: right; min-width: 0; }
.filename {
  font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.yes { color: var(--success); }

.tags { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.tag {
  display: inline-flex; align-items: center; min-height: 32px; padding: 0 var(--space-3);
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-full);
  color: var(--text-secondary); font-size: var(--text-sm); text-decoration: none;
}
.tag:hover { background: var(--surface-hover); color: var(--text); }

.section-head { display: flex; align-items: baseline; justify-content: space-between;
                gap: var(--space-3); margin-bottom: var(--space-3); }
.section-head h2 { margin: 0; }
.tally { font-size: var(--text-sm); color: var(--text-secondary); }

.latest { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.latest-item {
  position: relative; display: grid; gap: var(--space-1);
  padding: var(--space-3) var(--space-4) var(--space-2);
  background: var(--surface); border: 1px solid var(--border);
  /* The pen it was marked with, as the card's edge; page notes keep a neutral one. */
  border-left: 4px solid var(--border);
  border-radius: var(--radius);
  transition: box-shadow var(--duration-fast) var(--ease);
}
.latest-item:hover { box-shadow: var(--shadow-md); }
.pen-yellow { border-left-color: var(--hl-yellow); }
.pen-green { border-left-color: var(--hl-green); }
.pen-blue { border-left-color: var(--hl-blue); }
.pen-pink { border-left-color: var(--hl-pink); }
.latest-passage {
  margin: 0; font-family: var(--font-serif); font-size: var(--text-md); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.latest-note { margin: 0; font-size: var(--text-base); }
.latest-kind {
  display: block; font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}
.latest-own {
  margin: 0; font-size: var(--text-sm); color: var(--text-secondary);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.latest-page {
  justify-self: start; min-height: 28px; display: inline-flex; align-items: center;
  font-size: var(--text-sm); font-weight: 500; color: var(--accent-text); text-decoration: none;
}
/* Stretched over the card: anywhere on it opens the passage. */
.latest-page::after { content: ""; position: absolute; inset: 0; }
.latest-page:focus-visible { outline: none; }
.latest-page:focus-visible::after { outline: 2px solid var(--focus); outline-offset: 2px;
                                    border-radius: var(--radius); }

.note-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.action {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: var(--tap-target); padding: 0 var(--space-4);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--radius-sm); box-shadow: var(--shadow-sm);
  font-size: var(--text-base); font-weight: 500; text-decoration: none;
}
.action:hover { background: var(--surface-hover); color: var(--text); }
/* Export is the rarer of the two, so it does not ask for the same attention. */
.action.quiet { background: transparent; border-color: transparent; box-shadow: none;
                color: var(--text-secondary); }
.action.quiet:hover { background: var(--surface-hover); color: var(--text); }

@media (max-width: 48rem) {
  .columns { grid-template-columns: minmax(0, 1fr); gap: var(--space-5); }
  .side { flex-direction: row; align-items: flex-start; gap: var(--space-4); }
  .hero { width: 132px; flex: none; }
  .cta { flex: 1; }
  .facts { grid-template-columns: minmax(0, 1fr); }
}
</style>
