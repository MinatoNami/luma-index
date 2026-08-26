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
const image = ref<HTMLImageElement | null>(null)

const pending = computed(() => !props.book.thumbnail_path)

const percent = computed(() => {
  const value = props.book.progress?.percentage ?? 0
  return Math.max(0, Math.min(100, value))
})
// Nothing to say about a book nobody has opened, and no room to say it on a
// thumbnail. A finished book keeps a full bar: that is information too.
const showProgress = computed(() => props.size !== 'sm' && percent.value > 0)
const src = computed(() => `/api/library/books/${props.book.id}/thumbnail`)

/**
 * Catch an image that finished loading before Vue got here.
 *
 * On a refresh the markup is server-rendered and the browser starts — often
 * finishes — fetching a cached cover before hydration attaches @load. That
 * event is then never seen, so `loaded` stayed false: the image was held at
 * opacity 0 with the shimmer on top, and the cover appeared stuck loading
 * forever. `complete` is the state the event would have announced.
 */
function syncWithElement() {
  const el = image.value
  if (!el || !el.complete) return
  // A complete image with no intrinsic width failed to decode.
  if (el.naturalWidth > 0) loaded.value = true
  else failed.value = true
}

// A shimmer that never resolves is a lie: it says "still coming" forever. If
// the image has not arrived by now, show the same placeholder a book without a
// cover gets, which is at least honest about there being nothing to display.
const STALL_AFTER_MS = 8000
let stallTimer: ReturnType<typeof setTimeout> | null = null

function watchForStall() {
  if (stallTimer) clearTimeout(stallTimer)
  stallTimer = setTimeout(() => {
    syncWithElement()
    if (!loaded.value) failed.value = true
  }, STALL_AFTER_MS)
}

onMounted(() => {
  syncWithElement()
  if (!loaded.value) watchForStall()
})

watch(loaded, (isLoaded) => {
  if (isLoaded && stallTimer) {
    clearTimeout(stallTimer)
    stallTimer = null
  }
})

onBeforeUnmount(() => stallTimer && clearTimeout(stallTimer))

watch(() => props.book.thumbnail_path, async () => {
  failed.value = false
  loaded.value = false
  // A changed cover may also already be cached.
  await nextTick()
  syncWithElement()
  if (!loaded.value) watchForStall()
})
</script>

<template>
  <div :class="['cover', props.size, { 'is-blank': pending || failed }]">
    <img v-if="!pending && !failed" ref="image" :src="src"
         :alt="`Cover of ${props.book.title}`"
         loading="lazy" decoding="async" :class="{ loaded }"
         @load="loaded = true" @error="failed = true" />
    <div v-if="pending || failed" class="blank">
      <AppIcon name="file" :size="props.size === 'sm' ? 16 : 22" />
      <span v-if="props.size !== 'sm'" class="hint">
        {{ pending ? 'Preparing…' : 'No preview' }}
      </span>
    </div>
    <div v-else-if="!loaded" class="shimmer" aria-hidden="true" />

    <!-- How far in you are, on the thing you recognise the book by. It was
         only ever in a text column before, which is a place you read rather
         than glance at. Hidden at sm: a 28px cover has no room for it. -->
    <div v-if="showProgress" class="progress" role="progressbar"
         :aria-valuenow="Math.round(percent)" aria-valuemin="0" aria-valuemax="100"
         :aria-label="`${Math.round(percent)}% read`">
      <div class="read" :style="{ width: `${percent}%` }" />
    </div>
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

/* Sits on the artwork, so the track is a scrim rather than a token colour: a
   surface colour would vanish into a pale cover and shout on a dark one. */
.progress {
  position: absolute; left: 0; right: 0; bottom: 0;
  height: 3px; background: rgb(0 0 0 / 28%);
}
.read { height: 100%; background: var(--accent); }

@keyframes shimmer { to { background-position: -200% 0; } }

@media (prefers-reduced-motion: reduce) {
  .shimmer { animation: none; }
  img { transition: none; }
}
</style>
