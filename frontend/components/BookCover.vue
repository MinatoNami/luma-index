<script setup lang="ts">
import type { Book } from '~/composables/useLibrary'

/**
 * A book's first page, rendered by the ingest worker.
 *
 * Three states, because covers arrive after the upload does: pending (the
 * worker has not reached this book yet), loaded, and failed. A book with no
 * cover still has to look like a book, so the fallback is a page-shaped card
 * rather than an empty box.
 */
const props = withDefaults(defineProps<{ book: Book; size?: 'sm' | 'md' | 'lg' }>(), {
  size: 'md',
})

const failed = ref(false)
const loaded = ref(false)

const pending = computed(() => !props.book.thumbnail_path)
const src = computed(() => `/api/library/books/${props.book.id}/thumbnail`)

watch(() => props.book.thumbnail_path, () => {
  failed.value = false
  loaded.value = false
})
</script>

<template>
  <div :class="['cover', props.size, { 'is-blank': pending || failed }]">
    <img v-if="!pending && !failed" :src="src" :alt="`Cover of ${props.book.title}`"
         loading="lazy" decoding="async" :class="{ loaded }"
         @load="loaded = true" @error="failed = true" />
    <div v-if="pending || failed" class="blank">
      <AppIcon name="file" :size="props.size === 'sm' ? 16 : 22" />
      <span v-if="props.size !== 'sm'" class="hint">
        {{ pending ? 'Preparing…' : 'No preview' }}
      </span>
    </div>
    <div v-else-if="!loaded" class="shimmer" aria-hidden="true" />
  </div>
</template>

<style scoped>
.cover {
  position: relative;
  overflow: hidden;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  /* A4-ish, so a page of text is not letterboxed. */
  aspect-ratio: 1 / 1.414;
  flex: none;
}

.sm { width: 28px; border-radius: 4px; }
.md { width: 100%; }
.lg { width: 100%; }

img {
  width: 100%; height: 100%; object-fit: cover; display: block;
  opacity: 0; transition: opacity var(--duration) var(--ease);
}
img.loaded { opacity: 1; }

.blank {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-2); color: var(--text-tertiary);
}
.hint { font-size: var(--text-xs); }

.shimmer {
  position: absolute; inset: 0;
  background: linear-gradient(90deg,
    var(--surface-sunken) 25%, var(--surface-hover) 50%, var(--surface-sunken) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s linear infinite;
}

@keyframes shimmer { to { background-position: -200% 0; } }

@media (prefers-reduced-motion: reduce) {
  .shimmer { animation: none; }
  img { transition: none; }
}
</style>
