import { localDate } from '~/composables/useNotebook'

/** Where a reader is: a zero-based page, and how far down it, 0–1. */
export interface ReadingPosition { page: number; fraction: number }

/**
 * The body of a PUT to `/library/books/<id>/progress`.
 *
 * One builder for every write, because there are two: the debounced one while
 * reading, and the last-gasp one when the page goes away. They were written
 * separately once, and the second drifted — it sent `fraction` where the
 * server reads `page_fraction`, and no timestamp at all — so the write that
 * was meant to catch a reader's final position never saved anything.
 */
export function progressBody(position: ReadingPosition, at: Date = new Date()) {
  return {
    page: position.page,
    page_fraction: position.fraction,
    // Lets the server drop this write if a later position already arrived
    // from another device.
    client_updated_at: at.toISOString(),
    // The day this page counts towards, on the reader's own calendar rather
    // than the server's UTC one — see library/activity.py. Here rather than at
    // one call site, so the last-gasp write on leaving counts it too.
    local_date: localDate(at),
  }
}
