import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
// Vite emits this and rewrites the URL, so the worker is served from our own
// origin. A CDN would be simpler and is exactly what the app's own rules forbid.
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

export type FitMode = 'fit-width' | 'fit-page' | number

let workerConfigured = false

function configureWorker() {
  if (workerConfigured) return
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
  workerConfigured = true
}

export interface LoadedPdf {
  doc: PDFDocumentProxy
  pageCount: number
  baseSize: { width: number; height: number }
}

export async function loadPdf(url: string): Promise<LoadedPdf> {
  configureWorker()
  const task = pdfjs.getDocument({
    url,
    withCredentials: true,
    // Ranged fetching is the whole reason the content endpoint learned to
    // answer 206: it lets a large book open on page one instead of after a
    // full download.
    disableAutoFetch: true,
    disableStream: false,
    // Bundled so CJK books render rather than showing blank glyphs.
    cMapUrl: '/cmaps/',
    cMapPacked: true,
  })
  const doc = await task.promise
  const first = await doc.getPage(1)
  const viewport = first.getViewport({ scale: 1 })
  first.cleanup()
  return {
    doc,
    pageCount: doc.numPages,
    baseSize: { width: viewport.width, height: viewport.height },
  }
}

/**
 * Renders pages on demand and throws away the ones that scrolled far enough
 * away.
 *
 * Retaining every page canvas is the fastest way to crash a tablet: a single
 * A4 page at 2x device pixel ratio is roughly 1600x2300x4 bytes, so a couple of
 * hundred pages is gigabytes. PRD §26 asks for exactly this and it is much
 * harder to retrofit than to build in.
 */
export class PageRenderer {
  private tasks = new Map<number, RenderTask>()
  private pages = new Map<number, PDFPageProxy>()

  constructor(readonly doc: PDFDocumentProxy) {}

  async page(number: number): Promise<PDFPageProxy> {
    let page = this.pages.get(number)
    if (!page) {
      page = await this.doc.getPage(number)
      this.pages.set(number, page)
    }
    return page
  }

  async render(number: number, canvas: HTMLCanvasElement, scale: number): Promise<void> {
    // A fast scroll queues renders faster than they complete; the stale ones
    // are worthless and would fight the current one for the main thread.
    this.cancel(number)

    const page = await this.page(number)
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const viewport = page.getViewport({ scale: scale * ratio })

    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    canvas.style.width = `${Math.floor(viewport.width / ratio)}px`
    canvas.style.height = `${Math.floor(viewport.height / ratio)}px`

    const context = canvas.getContext('2d', { alpha: false })
    if (!context) return

    const task = page.render({ canvasContext: context, viewport })
    this.tasks.set(number, task)
    try {
      await task.promise
    } catch (error: any) {
      // Cancelling is the normal outcome of scrolling, not a failure.
      if (error?.name !== 'RenderingCancelledException') throw error
    } finally {
      if (this.tasks.get(number) === task) this.tasks.delete(number)
    }
  }

  cancel(number: number) {
    const task = this.tasks.get(number)
    if (task) {
      task.cancel()
      this.tasks.delete(number)
    }
  }

  /** Free a page the reader has scrolled away from. */
  release(number: number) {
    this.cancel(number)
    const page = this.pages.get(number)
    if (page) {
      page.cleanup()
      this.pages.delete(number)
    }
  }

  destroy() {
    for (const number of [...this.tasks.keys()]) this.cancel(number)
    for (const number of [...this.pages.keys()]) this.release(number)
  }
}

export function scaleFor(
  mode: FitMode,
  base: { width: number; height: number },
  container: { width: number; height: number },
): number {
  if (typeof mode === 'number') return mode
  // Leave a little air so a fitted page is not flush against the chrome.
  const width = (container.width - 32) / base.width
  if (mode === 'fit-width') return Math.max(0.1, width)
  const height = (container.height - 32) / base.height
  return Math.max(0.1, Math.min(width, height))
}


/**
 * Draws the selectable text over a rendered page.
 *
 * PDF.js positions transparent spans on top of the canvas; the pixels come from
 * the canvas and the selection comes from these. Without it a PDF is a picture
 * of a book — nothing to select, nothing to search, and nothing for Phase 5's
 * highlights to anchor to.
 */
export async function renderTextLayer(
  page: PDFPageProxy,
  container: HTMLElement,
  scale: number,
): Promise<void> {
  container.replaceChildren()
  const viewport = page.getViewport({ scale })

  // v4 positions spans from this custom property rather than inline styles.
  container.style.setProperty('--scale-factor', String(scale))
  container.style.width = `${Math.floor(viewport.width)}px`
  container.style.height = `${Math.floor(viewport.height)}px`

  const layer = new pdfjs.TextLayer({
    textContentSource: await page.getTextContent(),
    container,
    viewport,
  })
  await layer.render()
}

/** The page's text as one string, for searching. */
export async function pageText(page: PDFPageProxy): Promise<string> {
  const content = await page.getTextContent()
  return content.items
    .map(item => ('str' in item ? item.str : ''))
    .join('')
}

export interface SearchMatch {
  page: number      // 1-indexed
  index: number     // character offset within that page's text
  text: string
}

/**
 * Searches page by page, reporting as it goes.
 *
 * A 535-page book is not something to extract in one blocking pass, so this
 * yields after each page and can be abandoned mid-way when the query changes.
 */
export async function* searchDocument(
  doc: PDFDocumentProxy,
  query: string,
  cache: Map<number, string>,
  signal: { cancelled: boolean },
): AsyncGenerator<{ page: number; matches: SearchMatch[]; done: boolean }> {
  const needle = query.trim().toLowerCase()
  if (!needle) return

  for (let number = 1; number <= doc.numPages; number += 1) {
    if (signal.cancelled) return

    let text = cache.get(number)
    if (text === undefined) {
      const page = await doc.getPage(number)
      text = await pageText(page)
      cache.set(number, text)
      page.cleanup()
    }

    const haystack = text.toLowerCase()
    const matches: SearchMatch[] = []
    let from = 0
    while (true) {
      const at = haystack.indexOf(needle, from)
      if (at === -1) break
      matches.push({ page: number, index: at, text: text.slice(at, at + needle.length) })
      from = at + needle.length
    }

    yield { page: number, matches, done: number === doc.numPages }
  }
}


/**
 * Turns a DOM text selection into quads in PDF user space.
 *
 * The browser reports the selection as viewport rectangles, which mean nothing
 * once the zoom changes. `convertToPdfPoint` maps them back into the
 * document's own coordinate system, where the same numbers describe the same
 * words on any screen at any scale — which is what PRD §23 asks for.
 */
export function selectionToQuads(
  selection: Selection,
  pageElement: HTMLElement,
  page: PDFPageProxy,
  scale: number,
): { quads: { x1: number; y1: number; x2: number; y2: number }[]; text: string } | null {
  if (selection.isCollapsed || selection.rangeCount === 0) return null

  const range = selection.getRangeAt(0)
  if (!pageElement.contains(range.commonAncestorContainer)) return null

  const text = selection.toString().trim()
  if (!text) return null

  const origin = pageElement.getBoundingClientRect()
  const viewport = page.getViewport({ scale })
  const quads: { x1: number; y1: number; x2: number; y2: number }[] = []

  for (const rect of range.getClientRects()) {
    // Sub-pixel rectangles are artefacts of line breaks, not selected text.
    if (rect.width < 1 || rect.height < 1) continue
    const [x1, y1] = viewport.convertToPdfPoint(rect.left - origin.left, rect.top - origin.top)
    const [x2, y2] = viewport.convertToPdfPoint(rect.right - origin.left,
                                                rect.bottom - origin.top)
    quads.push({ x1: Math.min(x1, x2), y1: Math.min(y1, y2),
                 x2: Math.max(x1, x2), y2: Math.max(y1, y2) })
  }

  return quads.length ? { quads, text } : null
}

/** The inverse: where a stored quad sits on screen at the current scale. */
export function quadToBox(
  quad: { x1: number; y1: number; x2: number; y2: number },
  page: PDFPageProxy,
  scale: number,
): { left: number; top: number; width: number; height: number } {
  const viewport = page.getViewport({ scale })
  const [ax, ay] = viewport.convertToViewportPoint(quad.x1, quad.y1)
  const [bx, by] = viewport.convertToViewportPoint(quad.x2, quad.y2)
  return {
    left: Math.min(ax, bx),
    top: Math.min(ay, by),
    width: Math.abs(bx - ax),
    height: Math.abs(by - ay),
  }
}
