<script setup lang="ts">
import type { Book } from '~/composables/useLibrary'
import type { Activity, DailyHighlight } from '~/composables/useNotebook'

/**
 * What you see when you open LumaIndex.
 *
 * It used to be the folder browser, which answers "what do I have" — a
 * question you ask occasionally. The question you ask most often is "where was
 * I", and the endpoint that answers it has existed since Phase 4 with nothing
 * calling it. So the browser moved to /library and this took the front door.
 */
const library = useLibrary()
const notebook = useNotebook()
const { user } = useAuth()

const { data, pending } = await useAsyncData('home', async () => {
  const [reading, recent] = await Promise.all([
    library.continueReading(),
    library.listBooks(null, { view: 'recent', limit: 12 }),
  ])
  return { reading, recent: recent.items }
}, { default: () => ({ reading: [] as Book[], recent: [] as Book[] }) })

/**
 * Activity and today's highlights, fetched in the browser rather than during
 * the server render.
 *
 * Both are about the reader's *today*, and only the browser knows what day it
 * is where they are: rendered on the server, a reader in Singapore would see
 * yesterday's streak until hydration corrected it. Neither is worth holding
 * the shelf back for, either — a failure leaves them out, not the page.
 */
const activity = ref<Activity | null>(null)
const daily = ref<DailyHighlight[]>([])

onMounted(async () => {
  const [a, d] = await Promise.allSettled([notebook.activity(), notebook.daily()])
  if (a.status === 'fulfilled') activity.value = a.value
  if (d.status === 'fulfilled') daily.value = d.value.results
})

// Someone who has never read a page and has no goal gets the "nothing on the
// go" prompt below, not a panel of zeros.
const showActivity = computed(() => {
  const a = activity.value
  return Boolean(a && (a.goal_pages || a.streak.longest || a.year.pages || a.year.books_finished))
})

const reading = computed(() => data.value?.reading ?? [])
// A book you are part way through is already on the shelf above; showing it
// twice makes the page look fuller and says less.
const recent = computed(() => {
  const started = new Set(reading.value.map(b => b.id))
  return (data.value?.recent ?? []).filter(b => !started.has(b.id))
})

const firstName = computed(() => {
  const name = user.value?.display_name?.trim()
  return name ? name.split(/\s+/)[0] : null
})

/**
 * When a book was last opened, in the terms someone would actually use.
 *
 * Exact timestamps are for records; this is a shelf, and "yesterday" is what
 * you would say out loud.
 */
function lastOpened(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  if (days < 14) return 'Last week'
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`
  return `${Math.floor(days / 30)} months ago`
}

function pageLabel(book: Book): string {
  if (!book.progress) return ''
  const page = book.progress.page + 1
  return book.page_count ? `Page ${page} of ${book.page_count}` : `Page ${page}`
}
</script>

<template>
  <main class="wrap">
    <header class="intro">
      <div>
        <h1>{{ firstName ? `Welcome back, ${firstName}` : 'Welcome back' }}</h1>
        <p v-if="reading.length" class="tertiary">
          {{ reading.length === 1 ? 'One book on the go.'
            : `${reading.length} books on the go.` }}
        </p>
      </div>
      <!-- A glance, not a dashboard: the book you came back for comes first. -->
      <ReadingToday v-if="showActivity && activity" :activity="activity" />
    </header>

    <div v-if="pending" class="skeletons">
      <div v-for="n in 3" :key="n" class="panel skeleton-card" />
    </div>

    <template v-else>
      <section v-if="reading.length" aria-labelledby="reading-heading">
        <div class="head">
          <h2 id="reading-heading">Continue reading</h2>
        </div>

        <ul class="reading">
          <li v-for="book in reading" :key="book.id" class="panel resume">
            <NuxtLink class="resume-open" :to="`/books/${book.id}`">
              <BookCover :book="book" size="md" class="thumb" />
              <span class="detail">
                <span class="title">{{ book.title }}</span>
                <span class="where">
                  <span class="numbers">
                    <span>{{ pageLabel(book) }}</span>
                    <span class="percent">{{ Math.round(book.progress?.percentage ?? 0) }}%</span>
                  </span>
                  <span class="meter">
                    <span class="fill" :style="{ width: `${book.progress?.percentage ?? 0}%` }" />
                  </span>
                  <span class="tertiary when">
                    {{ lastOpened(book.progress?.last_opened_at ?? null) }}
                  </span>
                </span>
              </span>
            </NuxtLink>
          </li>
        </ul>
      </section>

      <!-- Nothing started yet: say what to do, not that a list is empty. -->
      <EmptyState v-else icon="inbox" title="Nothing on the go"
                  description="Open a book and it will wait for you here, at the page you left it."
                  class="panel">
        <NuxtLink class="cta" to="/library">Browse the library</NuxtLink>
      </EmptyState>

      <!-- Readwise's daily review, without the review: a few things you once
           thought worth marking, the same few all day, different tomorrow. -->
      <section v-if="daily.length" aria-labelledby="daily-heading">
        <div class="head">
          <h2 id="daily-heading">From your notebook</h2>
          <NuxtLink class="quiet-link" to="/notebook">Open notebook</NuxtLink>
        </div>

        <ul class="daily">
          <li v-for="mark in daily" :key="mark.id" :class="['panel', 'quote', mark.colour]">
            <blockquote>{{ mark.text }}</blockquote>
            <p v-if="mark.note" class="quote-note">{{ mark.note }}</p>
            <!-- Stretched over the card: anywhere on it opens the passage. -->
            <NuxtLink class="quote-source" :to="`/books/${mark.book.id}?page=${mark.page + 1}`">
              <span class="quote-title">{{ mark.book.title }}</span>
              <span class="quote-page">Page {{ mark.page + 1 }}</span>
            </NuxtLink>
          </li>
        </ul>
      </section>

      <section v-if="showActivity && activity" aria-labelledby="week-heading">
        <div class="head">
          <h2 id="week-heading">This week</h2>
          <NuxtLink class="quiet-link" to="/settings#reading-goal">
            {{ activity.goal_pages ? 'Change goal' : 'Set a goal' }}
          </NuxtLink>
        </div>
        <ReadingWeek :activity="activity" />
      </section>

      <section v-if="recent.length" aria-labelledby="recent-heading">
        <div class="head">
          <h2 id="recent-heading">Recently added</h2>
          <NuxtLink class="quiet-link" to="/library?view=recent">See all</NuxtLink>
        </div>

        <ul class="recent">
          <li v-for="book in recent" :key="book.id">
            <NuxtLink class="cover-open" :to="`/books/${book.id}`">
              <BookCover :book="book" size="md" />
              <span class="title small">{{ book.title }}</span>
            </NuxtLink>
          </li>
        </ul>
      </section>
    </template>
  </main>
</template>

<style scoped>
.wrap {
  flex: 1; width: 100%; max-width: 76rem; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7);
  display: flex; flex-direction: column; gap: var(--space-6);
}

.intro {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: var(--space-4);
}
.intro h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; }
.intro p { margin: var(--space-1) 0 0; font-size: var(--text-base); }

.head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: var(--space-3); margin-bottom: var(--space-4);
}
.head h2 { margin: 0; font-size: var(--text-md); }

/* A link that looks like the primary button, because it is navigation and
   AppButton renders a <button>. Same tokens as AppButton.primary. */
.cta {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: var(--tap-target); padding: 0 var(--space-4);
  background: var(--accent); color: var(--on-accent);
  border-radius: var(--radius-sm);
  font-size: var(--text-base); font-weight: 500; text-decoration: none;
}
.cta:hover { background: var(--accent-hover); color: var(--on-accent); }

/* -- continue reading ----------------------------------------------------- */

.reading {
  list-style: none; margin: 0; padding: 0;
  display: grid; gap: var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
}

.resume { padding: var(--space-4); }
.resume-open {
  display: flex; gap: var(--space-4);
  color: inherit; text-decoration: none;
}
/* Fixed rather than fluid: these sit beside text, so a wide card must not
   turn its cover into a poster. */
.thumb { width: 84px; flex: none; }
/* The card already says how far in you are, in numbers and in a meter. A third
   copy on the cover is noise; the grid, where there are no numbers, keeps it. */
.thumb :deep(.progress) { display: none; }

.detail { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: var(--space-2); }
.title {
  font-size: var(--text-base); font-weight: 500; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.where { margin-top: auto; display: grid; gap: var(--space-2); }
.numbers {
  display: flex; justify-content: space-between; gap: var(--space-2);
  font-size: var(--text-xs); color: var(--text-secondary);
}
.percent { color: var(--accent-text); font-weight: 500; }
.meter {
  height: 4px; border-radius: var(--radius-full);
  background: var(--surface-sunken); overflow: hidden;
}
.fill { display: block; height: 100%; background: var(--accent); border-radius: var(--radius-full); }
.when { font-size: var(--text-xs); }

/* -- recently added ------------------------------------------------------- */

.recent {
  list-style: none; margin: 0; padding: 0;
  display: grid; gap: var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
}
.cover-open {
  display: grid; gap: var(--space-2);
  color: inherit; text-decoration: none;
}
.title.small { font-size: var(--text-sm); -webkit-line-clamp: 2; }

/* -- from your notebook --------------------------------------------------- */

.daily {
  list-style: none; margin: 0; padding: 0;
  display: grid; gap: var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.quote {
  position: relative; overflow: hidden;
  display: flex; flex-direction: column; gap: var(--space-3);
  padding: var(--space-4) var(--space-4) var(--space-3) var(--space-5);
  transition: border-color var(--duration-fast) var(--ease),
              box-shadow var(--duration-fast) var(--ease);
}
.quote:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
/* The pen the passage was marked with, down the edge. */
.quote::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.quote.yellow::before { background: var(--hl-yellow); }
.quote.green::before { background: var(--hl-green); }
.quote.blue::before { background: var(--hl-blue); }
.quote.pink::before { background: var(--hl-pink); }
/* The author's words in the book face; your note beneath, in the app's. */
.quote blockquote {
  margin: 0; font-family: var(--font-serif); font-size: 1.0625rem; line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden;
  white-space: pre-line; overflow-wrap: anywhere;
}
.quote-note {
  margin: 0; padding-left: var(--space-3); border-left: 2px solid var(--border);
  color: var(--text-secondary); font-size: var(--text-sm);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.quote-source {
  margin-top: auto; display: flex; align-items: baseline; gap: var(--space-2);
  min-height: 28px; padding-top: var(--space-1);
  font-size: var(--text-sm); color: var(--text-secondary); text-decoration: none;
}
.quote-source::after { content: ""; position: absolute; inset: 0; }
.quote-source:focus-visible { outline: none; }
.quote-source:focus-visible::after { outline: 2px solid var(--focus); outline-offset: -2px;
                                     border-radius: var(--radius-lg); }
.quote:hover .quote-title { color: var(--text); }
.quote-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
               font-weight: 500; }
.quote-page { flex: none; color: var(--accent-text); }

/* -- loading -------------------------------------------------------------- */

.skeletons {
  display: grid; gap: var(--space-4);
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
}
.skeleton-card { height: 148px; }

@media (max-width: 40rem) {
  .wrap { padding: var(--space-5) var(--space-4) var(--space-6); }
  .recent { grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); }
}
</style>
