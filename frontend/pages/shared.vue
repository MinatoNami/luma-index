<script setup lang="ts">
import { type SharedBook } from '~/composables/useLibrary'

const sharing = useSharing()
const { logout } = useAuth()

const { data: books } = await useAsyncData('shared-books',
  () => sharing.sharedWithMe().catch(() => [] as SharedBook[]))
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><AppLogo :size="24" /><strong>LumaIndex</strong></div>
      <div class="account">
        <NuxtLink class="quiet-link" to="/">My library</NuxtLink>
        <AppButton variant="ghost" size="sm" @click="logout">Sign out</AppButton>
      </div>
    </header>

    <main class="wrap">
      <h1>Shared with me</h1>
      <p class="muted">
        Books other people on this instance have shared. Your reading position
        and notes on them are your own.
      </p>

      <div v-if="books?.length" class="cards">
        <div v-for="book in books" :key="book.id" class="card panel">
          <NuxtLink class="card-open" :to="`/books/${book.id}`">
            <div class="cover">
              <img v-if="book.thumbnail_path" :src="`/api/library/books/${book.id}/thumbnail`"
                   :alt="`Cover of ${book.title}`" loading="lazy" />
              <AppIcon v-else name="file" :size="22" />
            </div>
            <span class="card-title">{{ book.title }}</span>
            <span class="card-meta tertiary">
              {{ book.owner_name }}
              <template v-if="book.page_count"> · {{ book.page_count }} pages</template>
            </span>
            <span v-if="book.progress" class="card-meta tertiary">
              {{ Math.round(book.progress.percentage) }}% read
            </span>
          </NuxtLink>
        </div>
      </div>

      <EmptyState v-else icon="inbox" title="Nothing shared yet"
                  description="When someone shares a book with this instance, it appears here." />
    </main>
  </div>
</template>

<style scoped>
.shell { min-height: 100dvh; }
.topbar { display: flex; align-items: center; justify-content: space-between;
          padding: var(--space-3) var(--space-5);
          background: var(--surface); border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-md); }
.account { display: flex; align-items: center; gap: var(--space-3); }
.quiet-link { color: var(--text-secondary); text-decoration: none; }
.quiet-link:hover { color: var(--text); }
.wrap { max-width: 72rem; margin: 0 auto; padding: var(--space-5);
        display: grid; gap: var(--space-4); align-content: start; }
h1 { font-size: var(--text-xl); margin: 0; }
.muted { color: var(--text-secondary); margin: 0; }
.cards { display: grid; gap: var(--space-4);
         grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
.cards > .card { max-width: 320px; padding: var(--space-3); }
.card-open { display: grid; gap: var(--space-2); text-decoration: none; color: inherit; }
.cover { aspect-ratio: 1 / 1.414; display: grid; place-items: center; overflow: hidden;
         background: var(--surface-sunken); border: 1px solid var(--border);
         border-radius: var(--radius-sm); color: var(--text-tertiary); }
.cover img { width: 100%; height: 100%; object-fit: cover; }
.card-title { font-size: var(--text-base); font-weight: 500;
              display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2;
              -webkit-box-orient: vertical; overflow: hidden; }
.card-meta { font-size: var(--text-xs); }
</style>
