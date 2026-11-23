import { describe, expect, it } from 'vitest'

import { progressBody } from '~/composables/readingProgress'
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
