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

/** A write as sent: the position, and the moment it was recorded. */
export interface ProgressWrite { position: ReadingPosition; at: Date }

/**
 * Which write to send now, if any.
 *
 * A new position always wins: it is the latest thing the reader did. With
 * none, a reader leaving the book — by closing the tab or by following a link
 * inside the app — resends the write already on its way but not yet
 * acknowledged: it may have failed, or the browser may cancel it along with
 * the page, and it was the reader's last position. It goes again with its
 * original timestamp, so it is the same write rather than a newer one, and a
 * position saved from another device meanwhile still wins over it.
 */
export function nextWrite(
  pending: ReadingPosition | null,
  inFlight: ProgressWrite | null,
  { leaving = false, now = new Date() }: { leaving?: boolean; now?: Date } = {},
): ProgressWrite | null {
  if (pending) return { position: pending, at: now }
  return leaving ? inFlight : null
}

/**
 * Why a save is being made, and so how it has to be sent.
 *
 * - `timer`: the debounced save while reading. Prepares CSRF if it must, and
 *   leaves an unacknowledged write alone — it is still on its way.
 * - `navigate`: leaving the reader inside the app (the book's details, the
 *   library). The page is not going anywhere, so CSRF can be awaited; but the
 *   reader is, so a kept write is resent — the component unmounts without any
 *   `pagehide` or `visibilitychange` to do it otherwise.
 * - `unload`: the tab closing or being hidden. Resends a kept write, and awaits
 *   nothing first, because nothing awaited then is sure to run.
 */
export type SaveReason = 'timer' | 'navigate' | 'unload'

export function savePlan(reason: SaveReason): { leaving: boolean; awaitCsrf: boolean } {
  return {
    leaving: reason !== 'timer',
    awaitCsrf: reason !== 'unload',
  }
}
