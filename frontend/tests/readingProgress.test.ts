import { describe, expect, it } from 'vitest'

import { nextWrite, progressBody, savePlan } from '~/composables/readingProgress'
import { localDate } from '~/composables/useNotebook'

/**
 * What a progress write says, in the shape `ProgressWriteSerializer` reads.
 *
 * The write sent as a tab closes once built its own body, and called the
 * fraction `fraction` — a name the server does not read — so the position it
 * existed to save was never saved. Both writes now share this builder; these
 * pin the names it uses to the ones the backend expects.
 */
describe('the body of a progress write', () => {
  const at = new Date('2026-11-21T07:30:00Z')

  it('names each field the way the server reads it', () => {
    expect(progressBody({ page: 12, fraction: 0.4 }, at)).toEqual({
      page: 12,
      page_fraction: 0.4,
      client_updated_at: '2026-11-21T07:30:00.000Z',
      local_date: localDate(at),
    })
  })

  it('carries the reader\'s own date, so the page counts towards their day', () => {
    // Built from the same moment as the timestamp, on the local calendar.
    expect(progressBody({ page: 1, fraction: 0 }, at).local_date).toBe(localDate(at))
    expect(progressBody({ page: 1, fraction: 0 }, at).local_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('never sends the reader-side name for the fraction', () => {
    expect(progressBody({ page: 0, fraction: 0 }, at)).not.toHaveProperty('fraction')
  })

  it('stamps the write with when it was made, so a stale one can be dropped', () => {
    const before = Date.now()
    const stamped = Date.parse(progressBody({ page: 3, fraction: 0.5 }).client_updated_at)
    expect(stamped).toBeGreaterThanOrEqual(before)
    expect(stamped).toBeLessThanOrEqual(Date.now())
  })
})

/**
 * What to send, and when. The case this exists for: the four-second save has
 * gone out, so nothing is pending, and the tab closes before the answer comes
 * back. The browser may cancel that request with the page; leaving must send
 * it again rather than find nothing to do.
 */
describe('which write to send', () => {
  const sent = { position: { page: 7, fraction: 0.5 }, at: new Date('2026-11-21T07:30:00Z') }
  const now = new Date('2026-11-21T07:30:09Z')

  it('sends a new position, stamped now', () => {
    expect(nextWrite({ page: 8, fraction: 0 }, null, { now }))
      .toEqual({ position: { page: 8, fraction: 0 }, at: now })
  })

  it('prefers a new position to one already on its way', () => {
    expect(nextWrite({ page: 9, fraction: 0 }, sent, { leaving: true, now })?.position.page)
      .toBe(9)
  })

  it('resends an unacknowledged write when the page is going away', () => {
    expect(nextWrite(null, sent, { leaving: true, now })).toBe(sent)
  })

  it('keeps the original timestamp, so it is the same write and not a newer one', () => {
    expect(nextWrite(null, sent, { leaving: true, now })?.at).toBe(sent.at)
  })

  it('does not resend while the reader is still on the page', () => {
    expect(nextWrite(null, sent, { now })).toBeNull()
  })

  it('has nothing to send when nothing is pending or outstanding', () => {
    expect(nextWrite(null, null, { leaving: true, now })).toBeNull()
  })
})

/**
 * How each kind of save is sent. The case from review on #3: a save fails,
 * then the reader opens the book's details inside the app. The reader
 * unmounts with no pagehide, so unless unmounting counts as leaving, the kept
 * write is never resent and the position is lost.
 */
describe('how a save is sent, by why it is made', () => {
  it('leaves an unconfirmed write alone while the reader is still reading', () => {
    expect(savePlan('timer')).toEqual({ leaving: false, awaitCsrf: true })
  })

  it('resends a kept write when leaving the reader inside the app, CSRF allowed', () => {
    expect(savePlan('navigate')).toEqual({ leaving: true, awaitCsrf: true })
  })

  it('resends a kept write as the tab goes away, awaiting nothing first', () => {
    expect(savePlan('unload')).toEqual({ leaving: true, awaitCsrf: false })
  })

  it('so a failed save followed by in-app navigation is sent again', () => {
    const failed = { position: { page: 7, fraction: 0.5 }, at: new Date('2026-11-21T07:30:00Z') }
    expect(nextWrite(null, failed, { leaving: savePlan('navigate').leaving })).toBe(failed)
  })
})
