<script setup lang="ts">
import { PageRenderer, clampScale, loadPdf, quadToBox, renderTextLayer, scaleFor, searchDocument,
         selectionToQuads, type FitMode, type SearchMatch } from '~/composables/usePdf'
import type { PDFDocumentProxy } from 'pdfjs-dist'

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
  openHighlight: [{ id: number; x: number; y: number }]
  /**
   * The scale actually in force, whenever it changes.
   *
   * `fit` goes in as a mode or a number; what comes out is the number, and the
   * toolbar needs it to step zoom from where the page really is rather than
   * from a guess.
   */
  scale: [number]
  /**
   * A scale the reader asked for by pinching or by a trackpad zoom.
   *
   * The component does not own `fit`, so it cannot zoom itself; it says what
   * the gesture meant and the page decides.
   */
  zoom: [number]
  /** Which way the reader is moving, for anything that hides while reading. */
  scrollDirection: [{ direction: 'up' | 'down'; atTop: boolean }]
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
  if (el instanceof HTMLElement) {
    hosts.set(number, el)
    return
  }
  // The element is gone, so whatever was drawn on it is gone too. Leaving the
  // page in `rendered` made renderPage return early the next time it was
  // needed — in single-page mode, where changing page replaces the element,
  // that meant a page could never be drawn again once left.
  hosts.delete(number)
  if (rendered.has(number)) {
    rendered.delete(number)
    renderer?.cancel(number)
  }
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
/**
 * Painted, but at the previous zoom.
 *
 * A zoom used to release every canvas and re-render from nothing, so each step
 * blanked the page and repainted it. These keep their pixels — stretched to the
 * new size, so they are soft for a moment — and are re-rendered at the new scale
 * behind that. `rendered` still says "there is something to look at", which is
 * what keeps the page-number placeholder from flashing over it.
 */
const stale = new Set<number>()

/**
 * How sharp each page is worth being, in device pixels per CSS pixel.
 *
 * Every page used to be capped at 2, which is a phone's screen giving back a
 * third of its resolution on the one page you are actually reading. Neighbours
 * keep that cap: they exist so a scroll has something to land on, they are
 * looked at in passing if at all, and they are the ones that add up.
 */
const FOCUSED_RATIO = 3
const NEARBY_RATIO = 2

// What each page has been asked for, so a page can be told it is now worth more
// than it got. Kept beside `rendered` and cleared with it.
const ratios = new Map<number, number>()

// A screen with fewer device pixels than this cannot use them, and asking for
// them would only make the canvas bigger than anything can show.
const nearbyRatio = () => Math.min(window.devicePixelRatio || 1, NEARBY_RATIO)
const focusedRatio = () => Math.min(window.devicePixelRatio || 1, FOCUSED_RATIO)

/**
 * Give the page you have settled on its extra pixels.
 *
 * Deliberately not during the scroll. Upgrading whichever page happens to be
 * nearest the top as the book goes past would render every page twice for a
 * view nobody stops to look at, and the second render is the expensive one.
 * Waiting for the scrolling to stop costs one page, once.
 */
const SETTLE = 250
let sharpenTimer: ReturnType<typeof setTimeout> | null = null

function scheduleSharpen() {
  if (sharpenTimer) clearTimeout(sharpenTimer)
  sharpenTimer = setTimeout(() => {
    sharpenTimer = null
    void renderPage(current.value, focusedRatio())
  }, SETTLE)
}

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

/** Whether this page's canvas is already good enough to leave alone. */
function upToDate(number: number, ratio: number): boolean {
  return rendered.has(number) && !stale.has(number) && (ratios.get(number) ?? 0) >= ratio
}

async function renderPage(number: number, ratio: number) {
  if (!renderer || upToDate(number, ratio)) return
  const host = hostFor(number)
  const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null
  if (!canvas) return

  rendered.add(number)
  // Recorded before the render, not after. A render in flight is already reason
  // enough not to start another on the same canvas — PDF.js refuses outright,
  // and the reader shows the refusal instead of the book. Recording the request
  // rather than what the budget granted also stops a page the budget cut down
  // being asked for the same upgrade on every pass.
  ratios.set(number, ratio)
  try {
    await renderer.render(number, canvas, scale.value, ratio)
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
    stale.delete(number)
  } catch (error: any) {
    rendered.delete(number)
    ratios.delete(number)
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
  if (!target?.dataset.highlight) return
  const box = target.getBoundingClientRect()
  emit('openHighlight', {
    id: Number(target.dataset.highlight),
    x: box.left + box.width / 2,
    y: box.bottom,
  })
}

/** A finished selection inside a page becomes quads the server can store. */
async function onSelectionEnd(event: MouseEvent | TouchEvent) {
  // The second finger of a pinch lifts through here too, and a stray selection
  // popup over a page you just zoomed is the last thing you want.
  if (pinching.value) return
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
  const host = hostFor(number)
  const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null

  // Not `rendered` alone. A render that throws — a cancellation counts — takes
  // its page out of the set on the way out, but the canvas was already sized
  // and allocated by then. Those pages were invisible to every later release:
  // out of the set, so this returned early, and eight megabytes each stayed
  // allocated for as long as the reader was open. An inline width is the mark
  // of a canvas that has been sized, and it is removed below.
  if (!rendered.has(number) && !canvas?.style.width) return

  rendered.delete(number)
  stale.delete(number)
  ratios.delete(number)
  renderer?.release(number)
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
  for (const number of wanted) renderPage(number, nearbyRatio())
  scheduleSharpen()

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
// Where the last direction call was made from, and how far we have travelled
// since. A threshold rather than raw deltas: a trackpad or a thumb resting on
// the glass produces a stream of one-pixel moves in both directions, and
// reporting each one would make anything listening flicker.
const DIRECTION_THRESHOLD = 24
// Far enough down that hiding chrome does not fight the top of the document.
const NEAR_TOP = 8
let lastScrollTop = 0
let travelled = 0
let reportedDirection: 'up' | 'down' = 'up'

function reportDirection() {
  const el = viewport.value
  if (!el) return

  const top = el.scrollTop
  const delta = top - lastScrollTop
  lastScrollTop = top

  if (top <= NEAR_TOP) {
    // The top always reports 'up', whatever the accumulated travel says: the
    // bar has to come back when the reader returns to the start of the book.
    travelled = 0
    if (reportedDirection === 'up') return
    reportedDirection = 'up'
    emit('scrollDirection', { direction: 'up', atTop: true })
    return
  }

  // Travel resets whenever the direction changes, so a reversal starts
  // counting from where it turned rather than from the last report.
  if ((delta > 0) !== (travelled > 0)) travelled = 0
  travelled += delta

  if (Math.abs(travelled) < DIRECTION_THRESHOLD) return

  const direction = travelled > 0 ? 'down' : 'up'
  travelled = 0
  if (direction === reportedDirection) return
  reportedDirection = direction
  emit('scrollDirection', { direction, atTop: false })
}

function onScroll() {
  reportDirection()
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0
    updateWindow()
  })
}

async function goTo(page: number, fraction = 0) {
  const clamped = Math.min(Math.max(1, page), total.value)
  current.value = clamped

  if (props.mode === 'single') {
    // Reported before the render, not after: the reader is on this page
    // whether or not it has finished painting, and waiting meant a slow or
    // failed render left the page counter showing the previous page.
    // updateWindow does not run in this mode, so without this, reading in
    // single-page mode would never save progress at all.
    emit('position', { page: clamped - 1, fraction: 0 })

    // Single-page mode renders only the current page, so changing it replaces
    // the element. Rendering before Vue has created the new one found nothing
    // to draw on and left the page blank.
    await nextTick()
    // Started, not awaited. Navigation must not queue behind painting, or a
    // slow page makes the next click feel broken — and a render that never
    // settles would block navigation entirely.
    void renderPage(clamped, focusedRatio())
    return
  }

  await nextTick()
  const el = hostFor(clamped)
  if (el && viewport.value) {
    viewport.value.scrollTop = el.offsetTop - viewport.value.offsetTop
      + fraction * el.getBoundingClientRect().height
  }
  updateWindow()
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
  doc: computed<PDFDocumentProxy | null>(() => renderer?.doc ?? null),
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
  if (sharpenTimer) clearTimeout(sharpenTimer)
})

/**
 * A zoom change invalidates every rendered canvas — but not what is on screen.
 *
 * The old canvas is stretched to the new size and left in place, so zooming
 * looks continuous instead of blanking between steps, and the sharp render
 * replaces it when it arrives. Stretched by resizing rather than by a transform:
 * a transform would leave the layout box at the old size and the pages would
 * overlap.
 */
watch(scale, async (next, previous) => {
  emit('scale', next)
  const factor = previous ? next / previous : 1

  // Only the canvas: the host is sized by pageStyle, which is already computed
  // from the new scale by the time this render lands.
  if (factor !== 1) {
    for (const number of rendered) {
      const canvas = hostFor(number)?.querySelector('canvas') as HTMLCanvasElement | null
      if (!canvas?.style.width) continue
      canvas.style.width = `${Number.parseFloat(canvas.style.width) * factor}px`
      canvas.style.height = `${Number.parseFloat(canvas.style.height) * factor}px`
      stale.add(number)
      ratios.delete(number)
    }
  }

  // A pinch or a trackpad zoom asked for this. Put back what was under the
  // pointer, now that the pages have their new size.
  if (pinchAnchor && viewport.value) {
    viewport.value.scrollLeft = factor * (pinchAnchor.scrollLeft + pinchAnchor.x) - pinchAnchor.x
    viewport.value.scrollTop = factor * (pinchAnchor.scrollTop + pinchAnchor.y) - pinchAnchor.y
    pinchAnchor = null
  }

  await nextTick()
  if (props.mode === 'single') void renderPage(current.value, focusedRatio())
  else updateWindow()
})

watch(() => props.mode, async () => {
  // Every rendered page belongs to the layout that is being replaced.
  for (const number of [...rendered]) releasePage(number)
  await nextTick()
  void goTo(current.value)
})

/* -- pinch and trackpad zoom -----------------------------------------------
 *
 * The browser's own pinch is no use here: it scales the whole app, chrome
 * included, and blows up the canvas that is already painted rather than
 * repainting it, so the text goes soft and stays soft. `touch-action` on the
 * viewport is what takes the gesture off the browser and gives it to us.
 *
 * During the gesture the page column is transformed — one cheap property, no
 * re-render — and the real render happens once, on release. A canvas cannot be
 * repainted at sixty frames a second, and does not need to be: the transform
 * scales the text and highlight layers with it, so everything stays lined up
 * and the only cost is that it is soft for the moment the fingers are down.
 */

// The page column, which is what gets transformed. The viewport must not be:
// it is the thing that scrolls.
const column = ref<HTMLElement | null>(null)

// Non-null while two fingers are down.
let pinch: {
  distance: number
  scrollLeft: number
  scrollTop: number
  x: number
  y: number
} | null = null

// The live scale factor, so the transform and the commit cannot disagree.
let pinchFactor = 1

// Where the viewport must end up once the new scale lands, so the point under
// the fingers stays under the fingers. Consumed by the scale watcher, which is
// the first moment the pages actually have their new size.
let pinchAnchor: { x: number; y: number; scrollLeft: number; scrollTop: number } | null = null

// Suppresses the selection popup, which would otherwise fire on the touchend
// that ends a pinch.
const pinching = ref(false)

function gestureIn(event: TouchEvent, element: HTMLElement) {
  const box = element.getBoundingClientRect()
  const [a, b] = [event.touches[0], event.touches[1]]
  return {
    distance: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1,
    scrollLeft: element.scrollLeft,
    scrollTop: element.scrollTop,
    x: (a.clientX + b.clientX) / 2 - box.left,
    y: (a.clientY + b.clientY) / 2 - box.top,
  }
}

function onTouchStart(event: TouchEvent) {
  if (event.touches.length !== 2 || !viewport.value) return
  pinch = gestureIn(event, viewport.value)
  pinchFactor = 1
  pinching.value = true
}

function onTouchMove(event: TouchEvent) {
  if (!pinch || event.touches.length !== 2) return
  // Ours now. Without this the viewport scrolls under the gesture as well as
  // scaling, and the page slides away from the fingers holding it.
  event.preventDefault()

  const [a, b] = [event.touches[0], event.touches[1]]
  const distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
  pinchFactor = clampScale(scale.value * (distance / pinch.distance)) / scale.value

  // transform-origin is the column's own top-left, and the translate is what
  // pins the gesture's midpoint in place. Anchoring by transform-origin alone
  // would need the origin in the column's coordinates, which change as it
  // scales; this does not.
  const x = (1 - pinchFactor) * (pinch.scrollLeft + pinch.x)
  const y = (1 - pinchFactor) * (pinch.scrollTop + pinch.y)
  if (column.value) {
    column.value.style.transformOrigin = '0 0'
    column.value.style.transform = `translate(${x}px, ${y}px) scale(${pinchFactor})`
  }
}

function onTouchEnd(event: TouchEvent) {
  // A third finger, or lifting one of three: not the end of anything.
  if (!pinch || event.touches.length >= 2) return

  const gesture = pinch
  const factor = pinchFactor
  pinch = null
  pinchFactor = 1
  if (column.value) {
    column.value.style.transform = ''
    column.value.style.transformOrigin = ''
  }
  // Let the touchend that ends the gesture pass before selection is live again.
  requestAnimationFrame(() => (pinching.value = false))

  const target = clampScale(scale.value * factor)
  // Two fingers that barely moved were a scroll, or a misfire. Re-rendering the
  // whole window for half a percent is not worth the flicker.
  if (Math.abs(target / scale.value - 1) < 0.01) return
  pinchAnchor = gesture
  emit('zoom', target)
}

function onWheel(event: WheelEvent) {
  // A trackpad pinch arrives as ctrl+wheel — that is how the platform reports
  // it — and so does ctrl+scroll on a mouse. Both mean zoom.
  if (!event.ctrlKey || !viewport.value) return
  event.preventDefault()

  const target = clampScale(scale.value * Math.exp(-event.deltaY / 180))
  if (Math.abs(target - scale.value) < 0.001) return

  const box = viewport.value.getBoundingClientRect()
  pinchAnchor = {
    x: event.clientX - box.left,
    y: event.clientY - box.top,
    scrollLeft: viewport.value.scrollLeft,
    scrollTop: viewport.value.scrollTop,
  }
  emit('zoom', target)
}

// Bound by hand rather than in the template, because both handlers call
// preventDefault and Vue gives no way to ask for a non-passive listener —
// which is exactly what the browser defaults these two to.
watch(viewport, (element, previous) => {
  previous?.removeEventListener('touchstart', onTouchStart)
  previous?.removeEventListener('touchmove', onTouchMove)
  previous?.removeEventListener('touchend', onTouchEnd)
  previous?.removeEventListener('touchcancel', onTouchEnd)
  previous?.removeEventListener('wheel', onWheel)
  if (!element) return
  element.addEventListener('touchstart', onTouchStart, { passive: true })
  element.addEventListener('touchmove', onTouchMove, { passive: false })
  element.addEventListener('touchend', onTouchEnd)
  element.addEventListener('touchcancel', onTouchEnd)
  element.addEventListener('wheel', onWheel, { passive: false })
}, { immediate: true, flush: 'post' })

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
  <!-- Focusable, because it scrolls. Without a tabindex a keyboard user could
       reach every button in the reader and still not move the page — axe calls
       this scrollable-region-focusable, and it was the one real keyboard
       failure here. PageUp/PageDown stay bound to page turns at the window
       level; the arrows and space scroll this natively. -->
  <div ref="viewport" class="viewport" tabindex="0"
       role="region" aria-label="Book pages"
       @scroll.passive="onScroll"
       @mouseup="onSelectionEnd" @touchend="onSelectionEnd">
    <p v-if="failed || pageError" class="notice notice-error" role="alert">
      <AppIcon name="warning" :size="17" /> {{ failed || pageError }}
    </p>

    <div v-else ref="column" class="pages" :class="[props.mode, { pinching }]">
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
  /* Panning stays the browser's; zooming is ours. Without this the browser
     takes the pinch and scales the whole app, chrome and all. */
  touch-action: pan-x pan-y;
}
.pages { display: flex; flex-direction: column; align-items: center;
         gap: var(--space-4); padding: var(--space-4); }
.pages.single { justify-content: center; min-height: 100%; }
/* Two fingers on a page should not drag a text selection across it. */
.pages.pinching { user-select: none; }
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
