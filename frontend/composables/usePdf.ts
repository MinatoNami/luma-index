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

  constructor(private doc: PDFDocumentProxy) {}

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
