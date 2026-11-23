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
  }
}

/** A write as sent: the position, and the moment it was recorded. */
export interface ProgressWrite { position: ReadingPosition; at: Date }

/**
 * Which write to send now, if any.
 *
 * A new position always wins: it is the latest thing the reader did. With
 * none, a page that is going away resends the write already on its way but
 * not yet acknowledged — the browser may cancel that request along with the
 * page, and it was the reader's last position. It goes again with its
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
