<script setup lang="ts">
import { PageRenderer, loadPdf, quadToBox, renderTextLayer, scaleFor, searchDocument,
         selectionToQuads, type FitMode, type SearchMatch } from '~/composables/usePdf'
import type { Highlight, Quad } from '~/composables/useAnnotations'

/**
 * The reader.
 *
 * Client-only by filename: it needs a canvas and a device pixel ratio, neither
 * of which exist during SSR.
 *
 * Pages are placeholders until they come near the viewport, and their canvases
 * are thrown away once they leave it — see PageRenderer for why that is not an
 * optimisation to add later.
 */
const props = defineProps<{
  src: string
  pageCount: number
  initialPage?: number
  initialFraction?: number
  mode: 'continuous' | 'single'
  fit: FitMode
  highlights?: Highlight[]
}>()

const emit = defineEmits<{
  position: [{ page: number; fraction: number }]
  loaded: [{ pageCount: number }]
  error: [string]
  select: [{ page: number; quads: Quad[]; text: string; x: number; y: number }]
  clearSelection: []
  openHighlight: [number]
}>()

// How many pages either side of the visible one keep their canvas.
const WINDOW = 2
// A hard ceiling, not an emergent one. Relying on the release branch to keep up
// with the render branch does not survive a fast scroll: measured on a
// 535-page book, that let 82 canvases and 468 MB accumulate. Whatever the
// scroll does, no more than this many pages hold pixels.
const MAX_RENDERED = 2 * WINDOW + 3

const viewport = ref<HTMLElement | null>(null)

// A Map maintained by a function ref, rather than `ref="pageEls"` on the v-for.
// An array ref is appended to on every render and never cleared, so it
// accumulates detached elements — and `find()` then returns a div that is no
// longer in the document, so zeroing its canvas frees nothing. That is what let
// 85 canvases and 580 MB survive a hard scroll.
const hosts = new Map<number, HTMLElement>()

function registerHost(number: number, el: Element | null) {
  if (el instanceof HTMLElement) hosts.set(number, el)
  else hosts.delete(number)
}

function hostFor(number: number): HTMLElement | undefined {
  const el = hosts.get(number)
  return el?.isConnected ? el : undefined
}
const loading = ref(true)
const failed = ref('')
const pageError = ref('')

const total = ref(props.pageCount || 0)
const current = ref((props.initialPage ?? 0) + 1)
const scale = ref(1)
const baseSize = ref({ width: 612, height: 792 })
const rendered = reactive(new Set<number>())

const query = ref('')
const matches = ref<SearchMatch[]>([])
const activeMatch = ref(-1)
const searching = ref(false)
const textCache = new Map<number, string>()
let searchSignal = { cancelled: false }

let renderer: PageRenderer | null = null
let observer: IntersectionObserver | null = null
let restored = false

const containerSize = ref({ width: 800, height: 900 })

function recomputeScale() {
  scale.value = scaleFor(props.fit, baseSize.value, containerSize.value)
}

watch(() => props.fit, recomputeScale)

// Placeholder dimensions, so the scrollbar is the right length before anything
// has rendered. Corrected per page as each one actually renders.
const pageStyle = computed(() => ({
  width: `${Math.round(baseSize.value.width * scale.value)}px`,
  height: `${Math.round(baseSize.value.height * scale.value)}px`,
}))

const visiblePages = computed(() =>
  props.mode === 'single' ? [current.value] : Array.from({ length: total.value }, (_, i) => i + 1),
)

async function renderPage(number: number) {
  if (!renderer || rendered.has(number)) return
  const host = hostFor(number)
  const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null
  if (!canvas) return

  rendered.add(number)
  try {
    await renderer.render(number, canvas, scale.value)
    // Correct the placeholder if this page is a different size from page one.
    if (host) {
      host.style.width = canvas.style.width
      host.style.height = canvas.style.height
    }

    const textLayer = host?.querySelector('.textLayer') as HTMLElement | null
    if (textLayer) {
      const page = await renderer.page(number)
      await renderTextLayer(page, textLayer, scale.value)
      if (query.value) markHits(textLayer)
    }
    await paintHighlights(number)
  } catch (error: any) {
    rendered.delete(number)
    // Shown, not just emitted. A page that silently fails to render is
    // indistinguishable from one that is still loading, which cost real time
    // to diagnose once already.
    pageError.value = error?.message || 'A page failed to render.'
    emit('error', pageError.value)
  } finally {
    // A render that lands after the last scroll pass still has to be paid for.
    scheduleBudget()
  }
}

/**
 * Position stored highlights over a rendered page.
 *
 * Projected from PDF user space on every render, which is what makes a
 * highlight land on the same words after a zoom change rather than drifting.
 */
async function paintHighlights(number: number) {
  const host = hostFor(number)
  const layer = host?.querySelector('.highlightLayer') as HTMLElement | null
  if (!layer || !renderer) return

  const forPage = (props.highlights ?? []).filter(h => h.page === number - 1)
  layer.replaceChildren()
  if (!forPage.length) return

  const page = await renderer.page(number)
  for (const highlight of forPage) {
    for (const quad of highlight.position_data?.quads ?? []) {
      const box = quadToBox(quad, page, scale.value)
      const mark = document.createElement('div')
      mark.className = `highlight-mark ${highlight.colour}`
      mark.style.left = `${box.left}px`
      mark.style.top = `${box.top}px`
      mark.style.width = `${box.width}px`
      mark.style.height = `${box.height}px`
      mark.dataset.highlight = String(highlight.id)
      if (highlight.note) mark.classList.add('has-note')
      mark.title = highlight.note || highlight.selected_text
      layer.append(mark)
    }
  }
}

function repaintAllHighlights() {
  for (const number of [...rendered]) paintHighlights(number)
}

watch(() => props.highlights, repaintAllHighlights, { deep: true })

function onLayerClick(event: MouseEvent) {
  const target = (event.target as HTMLElement).closest('.highlight-mark') as HTMLElement | null
  if (target?.dataset.highlight) emit('openHighlight', Number(target.dataset.highlight))
}

/** A finished selection inside a page becomes quads the server can store. */
async function onSelectionEnd(event: MouseEvent | TouchEvent) {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed) {
    emit('clearSelection')
    return
  }

  const anchor = selection.anchorNode
  const host = [...hosts.values()].find(el => el.contains(anchor as Node))
  if (!host || !renderer) {
    emit('clearSelection')
    return
  }

  const number = Number(host.dataset.page)
  const page = await renderer.page(number)
  const result = selectionToQuads(selection, host, page, scale.value)
  if (!result) {
    emit('clearSelection')
    return
  }

  const point = 'changedTouches' in event && event.changedTouches.length
    ? event.changedTouches[0]
    : (event as MouseEvent)
  emit('select', {
    page: number - 1,
    quads: result.quads,
    text: result.text,
    x: point.clientX,
    y: point.clientY,
  })
}

function releasePage(number: number) {
  if (!rendered.has(number)) return
  rendered.delete(number)
  renderer?.release(number)
  const host = hostFor(number)
  const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null
  if (canvas) {
    // Zeroing the canvas is what actually frees the backing store; removing the
    // element alone leaves it to the garbage collector's discretion.
    canvas.width = 0
    canvas.height = 0
    canvas.style.removeProperty('width')
    canvas.style.removeProperty('height')
  }
  if (host) {
    // renderPage pins the host to the rendered size. Clearing it hands sizing
    // back to pageStyle, so a released page follows the current zoom instead of
    // staying as wide as it was when it last rendered.
    host.style.removeProperty('width')
    host.style.removeProperty('height')
    // The text layer is as expensive to keep as the canvas.
    host.querySelector('.textLayer')?.replaceChildren()
    host.querySelector('.highlightLayer')?.replaceChildren()
  }
}

function updateWindow() {
  if (!viewport.value || props.mode === 'single') return
  const bounds = viewport.value.getBoundingClientRect()

  // Which page is the reader actually looking at? Decided before anything is
  // rendered or released, so both decisions use the same answer — previously
  // the loop compared against a `current` it was still in the middle of
  // updating.
  let closest = current.value
  let closestDistance = Infinity
  const visible = new Set<number>()

  for (const [number, el] of hosts) {
    if (!el.isConnected) continue
    const rect = el.getBoundingClientRect()
    if (rect.bottom > bounds.top && rect.top < bounds.bottom) {
      visible.add(number)
      const distance = Math.abs(rect.top - bounds.top)
      if (distance < closestDistance) {
        closestDistance = distance
        closest = number
      }
    }
  }

  if (closest !== current.value) current.value = closest

  // Render what is on screen and a little either side.
  const wanted = new Set(visible)
  for (let offset = -WINDOW; offset <= WINDOW; offset += 1) {
    const number = closest + offset
    if (number >= 1 && number <= total.value) wanted.add(number)
  }
  for (const number of wanted) renderPage(number)

  enforceBudget(closest, wanted)
  emitPosition()
}

/**
 * Keep at most MAX_RENDERED pages holding pixels.
 *
 * Called after renders finish as well as on scroll: a render is async and adds
 * itself to `rendered` before it completes, so a fast scroll finishes with more
 * pages in flight than the last scroll-driven pass could see. Trimming only on
 * scroll left 28 canvases and 187 MB after a hard flick through a 535-page book.
 */
function enforceBudget(closest = current.value, keep?: Set<number>) {
  const wanted = keep ?? new Set(
    Array.from({ length: WINDOW * 2 + 1 }, (_, i) => closest - WINDOW + i),
  )

  const surplus = [...rendered]
    .filter(number => !wanted.has(number))
    .sort((a, b) => Math.abs(b - closest) - Math.abs(a - closest))

  for (const number of surplus) {
    if (rendered.size <= MAX_RENDERED) break
    releasePage(number)
  }
  // Anything well outside the window goes regardless of the count.
  for (const number of [...rendered]) {
    if (!wanted.has(number) && Math.abs(number - closest) > WINDOW + 2) releasePage(number)
  }
}

let budgetTimer: ReturnType<typeof setTimeout> | null = null
function scheduleBudget() {
  if (budgetTimer) return
  budgetTimer = setTimeout(() => {
    budgetTimer = null
    enforceBudget()
  }, 150)
}

function emitPosition() {
  const el = hostFor(current.value)
  if (!el || !viewport.value) return
  const rect = el.getBoundingClientRect()
  const top = viewport.value.getBoundingClientRect().top
  // How far into this page the reading point sits — the part that survives a
  // zoom change, unlike a pixel offset.
  const fraction = rect.height ? Math.min(1, Math.max(0, (top - rect.top) / rect.height)) : 0
  emit('position', { page: current.value - 1, fraction })
}

let scrollFrame = 0
function onScroll() {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0
    updateWindow()
  })
}

function goTo(page: number, fraction = 0) {
  const clamped = Math.min(Math.max(1, page), total.value)
  current.value = clamped
  if (props.mode === 'single') {
    renderPage(clamped)
    return
  }
  nextTick(() => {
    const el = hostFor(clamped)
    if (el && viewport.value) {
      viewport.value.scrollTop = el.offsetTop - viewport.value.offsetTop
        + fraction * el.getBoundingClientRect().height
    }
    updateWindow()
  })
}

/** Wrap occurrences of the query inside an already-rendered text layer. */
function markHits(layer: HTMLElement) {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return

  for (const span of layer.querySelectorAll('span')) {
    const text = span.textContent ?? ''
    if (!text.toLowerCase().includes(needle)) continue

    const fragment = document.createDocumentFragment()
    let from = 0
    while (true) {
      const at = text.toLowerCase().indexOf(needle, from)
      if (at === -1) break
      fragment.append(text.slice(from, at))
      const hit = document.createElement('span')
      hit.className = 'search-hit'
      hit.textContent = text.slice(at, at + needle.length)
      fragment.append(hit)
      from = at + needle.length
    }
    fragment.append(text.slice(from))
    span.replaceChildren(fragment)
  }
}

function remarkVisible() {
  for (const [number, el] of hosts) {
    if (!rendered.has(number) || !el.isConnected) continue
    const layer = el.querySelector('.textLayer') as HTMLElement | null
    if (!layer) continue
    // Re-render the layer from scratch, since marking rewrites its spans.
    renderer?.page(number).then(page => renderTextLayer(page, layer, scale.value)
      .then(() => query.value && markHits(layer)))
  }
}

async function runSearch(term: string) {
  searchSignal.cancelled = true
  searchSignal = { cancelled: false }
  const signal = searchSignal

  query.value = term
  matches.value = []
  activeMatch.value = -1

  if (!term.trim() || !renderer) {
    searching.value = false
    remarkVisible()
    return
  }

  searching.value = true
  const doc = renderer.doc
  const found: SearchMatch[] = []

  for await (const batch of searchDocument(doc, term, textCache, signal)) {
    if (signal.cancelled) return
    if (batch.matches.length) {
      found.push(...batch.matches)
      matches.value = [...found]
      // Jump to the first hit as soon as there is one, rather than making the
      // reader wait for a 535-page sweep to finish.
      if (activeMatch.value === -1) selectMatch(0)
    }
  }
  searching.value = false
  remarkVisible()
}

function selectMatch(index: number) {
  if (!matches.value.length) return
  const wrapped = (index + matches.value.length) % matches.value.length
  activeMatch.value = wrapped
  goTo(matches.value[wrapped].page)
  nextTick(remarkVisible)
}

defineExpose({
  doc: computed(() => renderer?.doc ?? null),
  repaintHighlights: repaintAllHighlights,
  goTo,
  next: () => goTo(current.value + 1),
  previous: () => goTo(current.value - 1),
  search: runSearch,
  nextMatch: () => selectMatch(activeMatch.value + 1),
  previousMatch: () => selectMatch(activeMatch.value - 1),
  matchCount: computed(() => matches.value.length),
  activeMatchIndex: computed(() => activeMatch.value),
  searching: computed(() => searching.value),
})

onMounted(async () => {
  try {
    const { doc, pageCount, baseSize: size } = await loadPdf(props.src)
    renderer = new PageRenderer(doc)
    total.value = pageCount
    baseSize.value = size
    emit('loaded', { pageCount })

    if (viewport.value) {
      const rect = viewport.value.getBoundingClientRect()
      containerSize.value = { width: rect.width, height: rect.height }
    }
    recomputeScale()
    loading.value = false

    await nextTick()
    if (!restored && props.initialPage) {
      restored = true
      goTo(props.initialPage + 1, props.initialFraction ?? 0)
    } else {
      updateWindow()
    }

    observer = new IntersectionObserver(() => updateWindow(), {
      root: viewport.value,
      rootMargin: '150% 0px',
    })
    for (const el of hosts.values()) observer.observe(el)
  } catch (error: any) {
    failed.value = error?.message || 'This PDF could not be opened.'
    loading.value = false
    emit('error', failed.value)
  }
})

onBeforeUnmount(() => {
  searchSignal.cancelled = true
  hosts.clear()
  observer?.disconnect()
  renderer?.destroy()
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  if (budgetTimer) clearTimeout(budgetTimer)
})

// A zoom change invalidates every rendered canvas.
watch(scale, () => {
  for (const number of [...rendered]) releasePage(number)
  nextTick(updateWindow)
})

watch(() => props.mode, () => nextTick(() => goTo(current.value)))

// A ResizeObserver rather than a window resize listener, because opening the
// contents sidebar narrows the stage without the window changing size at all —
// which left a fitted page wider than its container.
//
// Attached by watching the ref rather than in onMounted: the element is not
// there yet when a synchronous mounted hook runs, so an observer created there
// silently observes nothing. That failure is invisible — no error, the page
// simply stops re-fitting — so it is worth attaching defensively.
let resizeObserver: ResizeObserver | null = null

watch(viewport, (element) => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!element || typeof ResizeObserver === 'undefined') return

  resizeObserver = new ResizeObserver(([entry]) => {
    const { width, height } = entry.contentRect
    if (!width || !height) return
    if (Math.abs(width - containerSize.value.width) < 1
        && Math.abs(height - containerSize.value.height) < 1) return
    containerSize.value = { width, height }
    recomputeScale()
  })
  resizeObserver.observe(element)
}, { immediate: true, flush: 'post' })

onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <div ref="viewport" class="viewport"
       @scroll.passive="onScroll"
       @mouseup="onSelectionEnd" @touchend="onSelectionEnd">
    <p v-if="failed || pageError" class="notice notice-error" role="alert">
      <AppIcon name="warning" :size="17" /> {{ failed || pageError }}
    </p>

    <div v-else class="pages" :class="props.mode">
      <div v-for="number in visiblePages" :key="number" class="page"
           :ref="el => registerHost(number, el as Element | null)"
           :data-page="number" :style="pageStyle">
        <canvas />
        <div class="highlightLayer" @click="onLayerClick" />
        <div class="textLayer" />
        <span v-if="!rendered.has(number)" class="page-number">{{ number }}</span>
      </div>
    </div>

    <div v-if="loading" class="loading">
      <span class="spinner" aria-hidden="true" />
      <span>Opening…</span>
    </div>
  </div>
</template>

<style scoped>
.viewport {
  position: relative;
  height: 100%;
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--surface-sunken);
}
.pages { display: flex; flex-direction: column; align-items: center;
         gap: var(--space-4); padding: var(--space-4); }
.pages.single { justify-content: center; min-height: 100%; }
.page {
  position: relative;
  background: #fff;
  box-shadow: var(--shadow-md);
  border-radius: 2px;
  display: grid;
  place-items: center;
  flex: none;
}
.page canvas { display: block; border-radius: 2px; position: relative; z-index: 0; }

/* Under the text layer, so selection still works over a highlight. */
.highlightLayer { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
:deep(.highlight-mark) {
  position: absolute;
  border-radius: 2px;
  pointer-events: auto;
  cursor: pointer;
  mix-blend-mode: multiply;
}
:deep(.highlight-mark.yellow) { background: rgb(255 214 79 / 55%); }
:deep(.highlight-mark.green)  { background: rgb(126 217 148 / 55%); }
:deep(.highlight-mark.blue)   { background: rgb(130 177 255 / 55%); }
:deep(.highlight-mark.pink)   { background: rgb(255 156 196 / 55%); }
:deep(.highlight-mark.has-note) { box-shadow: inset 0 -2px 0 rgb(0 0 0 / 35%); }
.page-number {
  position: absolute; color: var(--text-tertiary); font-size: var(--text-sm);
}
.loading, .notice { position: absolute; inset-inline: 0; top: 40%; margin: 0 auto;
                    width: max-content; }
.loading { display: flex; align-items: center; gap: var(--space-3);
           color: var(--text-secondary); }
.spinner {
  width: 16px; height: 16px; border-radius: 50%;
  border: 2px solid currentColor; border-top-color: transparent;
  animation: spin 620ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .spinner { animation-duration: 2s; }
}
</style>
