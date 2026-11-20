<script setup lang="ts">
import { formatBytes } from '~/composables/useLibrary'

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

          <section aria-labelledby="notes-heading">
            <h2 id="notes-heading">Your notes</h2>
            <ul v-if="annotationTotal" class="counts">
              <li class="panel">
                <strong>{{ book.annotations.highlights }}</strong>
                <span>{{ book.annotations.highlights === 1 ? 'Highlight' : 'Highlights' }}</span>
              </li>
              <li class="panel">
                <strong>{{ book.annotations.bookmarks }}</strong>
                <span>{{ book.annotations.bookmarks === 1 ? 'Bookmark' : 'Bookmarks' }}</span>
              </li>
              <li class="panel">
                <strong>{{ book.annotations.notes }}</strong>
                <span>{{ book.annotations.notes === 1 ? 'Page note' : 'Page notes' }}</span>
              </li>
            </ul>
            <div v-if="annotationTotal" class="note-actions">
              <NuxtLink class="action" :to="`/notebook?book=${book.id}`">
                <AppIcon name="notebook" :size="16" /> Open in notebook
              </NuxtLink>
              <!-- Markdown, because it is what Obsidian, Logseq and a plain
                   editor all take without a plugin. -->
              <a class="action" :href="notebook.exportUrl(book.id)" download>
                <AppIcon name="download" :size="16" /> Export as Markdown
              </a>
            </div>
            <p v-else class="tertiary">
              Nothing yet. Select text while reading to highlight it.
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

.counts { list-style: none; margin: 0; padding: 0; display: flex; gap: var(--space-3); }
.counts li { flex: 1; padding: var(--space-3) var(--space-4); }
.counts strong { display: block; font-size: var(--text-xl); letter-spacing: -0.02em; }

.note-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.action {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: var(--tap-target); padding: 0 var(--space-4);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--radius-sm); box-shadow: var(--shadow-sm);
  font-size: var(--text-base); font-weight: 500; text-decoration: none;
}
.action:hover { background: var(--surface-hover); color: var(--text); }
.counts span { font-size: var(--text-sm); color: var(--text-secondary); }

@media (max-width: 48rem) {
  .columns { grid-template-columns: minmax(0, 1fr); gap: var(--space-5); }
  .side { flex-direction: row; align-items: flex-start; gap: var(--space-4); }
  .hero { width: 132px; flex: none; }
  .cta { flex: 1; }
  .facts { grid-template-columns: minmax(0, 1fr); }
}
</style>
