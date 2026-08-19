<script setup lang="ts">
import type { Folder } from '~/composables/useLibrary'

/**
 * A folder wearing the covers of the books inside it.
 *
 * The tiles are the same per-book thumbnails the grid already shows — the API
 * sends ids, not a composited image — so a folder whose contents changed looks
 * right on the very next render, with no stored picture to invalidate.
 *
 * Deliberately no loading state. A cover that is still arriving leaves its
 * slot showing the folder tint, which is what an empty slot looks like anyway;
 * the alternative is a per-tile shimmer, and a shimmer whose load event goes
 * missing is the bug that has already been fixed twice in BookCover.
 */
const props = withDefaults(defineProps<{ folder: Folder; size?: 'md' | 'lg' }>(), {
  size: 'md',
})

const failed = ref<number[]>([])

// Four cells always, however many covers there are: the empty ones show the
// folder's own tint, which is what keeps a folder card from reading as a book.
const CELLS = 4

const covers = computed(() =>
  (props.folder.preview_book_ids ?? []).filter((id) => !failed.value.includes(id)).slice(0, CELLS),
)
const cells = computed(() =>
  Array.from({ length: CELLS }, (_, index) => covers.value[index] ?? null),
)
const empty = computed(() => covers.value.length === 0)

// Narrowing a `v-if` into an event handler on the same element is not
// something vue-tsc will do for us, so the null check lives here.
function markFailed(id: number | null) {
  if (id !== null && !failed.value.includes(id)) failed.value.push(id)
}

watch(() => props.folder.preview_book_ids, () => { failed.value = [] })
</script>

<template>
  <div :class="['folder-cover', props.size, { 'is-empty': empty }]">
    <AppIcon v-if="empty" name="folder" :size="props.size === 'lg' ? 34 : 26" />
    <div v-else class="mosaic" aria-hidden="true">
      <span v-for="(id, index) in cells" :key="index" class="tile">
        <img v-if="id !== null" :src="`/api/library/books/${id}/thumbnail`" alt=""
             loading="lazy" decoding="async" @error="markFailed(id)" />
      </span>
    </div>
    <span class="corner" aria-hidden="true"><AppIcon name="folder" :size="13" /></span>
  </div>
</template>

<style scoped>
.folder-cover {
  position: relative;
  display: grid;
  place-items: center;
  /* Matched to BookCover so folders and books line up on one grid baseline. */
  aspect-ratio: 1 / 1.414;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  color: var(--accent-text);
  overflow: hidden;
}

.mosaic {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: var(--space-1);
  padding: var(--space-2);
  width: 100%;
  height: 100%;
}

/* Transparent, so an empty slot shows the folder's own tint. Filling it with
   a sunken colour instead punched near-black holes into the tint in dark mode,
   and a folder holding two books looked broken rather than half full. */
.tile { overflow: hidden; border-radius: 3px; }

img {
  width: 100%; height: 100%;
  object-fit: cover; display: block;
  animation: fade-in var(--duration) var(--ease);
}

/* The tint alone is a weak signal once four covers are sitting on top of it,
   so the folder says so outright. */
.corner {
  position: absolute; right: var(--space-1); bottom: var(--space-1);
  display: grid; place-items: center;
  width: 22px; height: 22px; border-radius: var(--radius-full);
  background: var(--surface); color: var(--accent-text);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.is-empty .corner { display: none; }

@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

@media (prefers-reduced-motion: reduce) {
  img { animation: none; }
}
</style>
