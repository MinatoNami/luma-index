<script setup lang="ts">
import type { PDFDocumentProxy } from 'pdfjs-dist'

/**
 * The page-thumbnail rail (PRD §20).
 *
 * Rendered lazily and bounded, for the same reason the main view is: a strip of
 * 535 thumbnails is still 535 canvases. Only what is scrolled into the rail
 * gets pixels, and the rest stay as numbered placeholders.
 */
const props = defineProps<{ doc: PDFDocumentProxy | null; pageCount: number; current: number }>()
const emit = defineEmits<{ select: [number] }>()

const WIDTH = 108
const MAX_THUMBS = 40

const rail = ref<HTMLElement | null>(null)
const hosts = new Map<number, HTMLElement>()
const drawn = reactive(new Set<number>())
let observer: IntersectionObserver | null = null

function register(number: number, el: Element | null) {
  if (el instanceof HTMLElement) {
    hosts.set(number, el)
    observer?.observe(el)
  } else {
    hosts.delete(number)
  }
}

// Drawing is serial and re-checked against visibility just before each render.
// Letting the observer start a draw per intersecting page queued hundreds at
// once: the trim then ran while renders were still in flight, and those
// in-flight renders resized the canvases it had just freed. 395 thumbnails
// survived a cap of 40.
const queue = new Set<number>()
let pumping = false

function request(number: number) {
  if (drawn.has(number)) return
  queue.add(number)
  pump()
}

function nearViewport(number: number): boolean {
  const host = hosts.get(number)
  const root = rail.value
  if (!host?.isConnected || !root) return false
  const a = host.getBoundingClientRect()
  const b = root.getBoundingClientRect()
  // Generous, but finite: a page that scrolled far away is not worth drawing.
  return a.bottom > b.top - 400 && a.top < b.bottom + 400
}

async function pump() {
  if (pumping) return
  pumping = true
  try {
    while (queue.size) {
      const number = queue.values().next().value as number
      queue.delete(number)
      if (!props.doc || drawn.has(number) || !nearViewport(number)) continue
      await draw(number)
      trim()
    }
  } finally {
    pumping = false
  }
}

async function draw(number: number) {
  const host = hosts.get(number)
  const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null
  if (!canvas || !host?.isConnected || !props.doc) return

  drawn.add(number)
  try {
    const page = await props.doc.getPage(number)
    const base = page.getViewport({ scale: 1 })
    const viewport = page.getViewport({ scale: WIDTH / base.width })
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    const context = canvas.getContext('2d', { alpha: false })
    if (context) await page.render({ canvasContext: context, viewport }).promise
    page.cleanup()
  } catch {
    drawn.delete(number)
  }
}

function trim() {
  if (drawn.size <= MAX_THUMBS) return
  const surplus = [...drawn]
    .sort((a, b) => Math.abs(b - props.current) - Math.abs(a - props.current))
  for (const number of surplus) {
    if (drawn.size <= MAX_THUMBS) break
    drawn.delete(number)
    const canvas = hosts.get(number)?.querySelector('canvas') as HTMLCanvasElement | null
    if (canvas) { canvas.width = 0; canvas.height = 0 }
  }
}

onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      const number = Number((entry.target as HTMLElement).dataset.page)
      if (number) request(number)
    }
  }, { root: rail.value, rootMargin: '200px 0px' })
  for (const el of hosts.values()) observer.observe(el)
})

onBeforeUnmount(() => {
  queue.clear()
  observer?.disconnect()
  hosts.clear()
})

// Keep the current page in view as the reader scrolls the document.
watch(() => props.current, (number) => {
  hosts.get(number)?.scrollIntoView({ block: 'nearest' })
})
</script>

<template>
  <aside ref="rail" class="rail" aria-label="Page thumbnails">
    <button v-for="number in props.pageCount" :key="number" type="button"
            :ref="el => register(number, el as Element | null)"
            :data-page="number" :class="['thumb', { current: number === props.current }]"
            :aria-current="number === props.current ? 'page' : undefined"
            @click="emit('select', number)">
      <canvas />
      <span class="label">{{ number }}</span>
    </button>
  </aside>
</template>

<style scoped>
.rail {
  width: 9.5rem; flex: none; overflow-y: auto; padding: var(--space-3);
  display: grid; gap: var(--space-3); align-content: start;
  background: var(--surface); border-inline-end: 1px solid var(--border);
}
.thumb {
  display: grid; justify-items: center; gap: var(--space-1);
  background: none; border: 0; padding: 0; cursor: pointer;
  color: var(--text-tertiary); font-size: var(--text-xs);
}
.thumb canvas {
  width: 108px; aspect-ratio: 1 / 1.414; object-fit: contain;
  background: #fff; border: 1px solid var(--border); border-radius: 2px;
}
.thumb.current canvas { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
.thumb.current .label { color: var(--accent-text); font-weight: 600; }
</style>
