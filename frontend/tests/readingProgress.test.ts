import { describe, expect, it } from 'vitest'

import { progressBody } from '~/composables/readingProgress'

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
    })
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
