import { describe, expect, it } from 'vitest'

import { lastCookie } from '~/composables/useApi'

/**
 * Which of two cookies of one name the app echoes back.
 *
 * Moving this instance under a path prefix rescoped both cookies from "/" to
 * the prefix, and a browser that held the old ones kept both — same name,
 * different path, so the new cookie joined the old rather than replacing it.
 * Django's parser keeps the last occurrence the request carried; this took the
 * first. The two ends of the CSRF handshake then compared different tokens and
 * every unsafe request failed: no folder could be created, nothing uploaded,
 * and the login that would have been the way out failed the same way.
 */
const CSRF = 'lumaindex_csrftoken'

describe('reading a cookie the app has to echo', () => {
  it('takes the last of a name, which is the one Django reads', () => {
    // How a browser serialises it: longest path first, so the stale cookie at
    // "/" is last — and last is what Django's parser keeps.
    expect(lastCookie(`${CSRF}=prefixed; ${CSRF}=stale`, CSRF)).toBe('stale')
  })

  it('reads a single cookie whatever company it keeps', () => {
    expect(lastCookie(`lumaindex_session=abc; ${CSRF}=token`, CSRF)).toBe('token')
    expect(lastCookie(`${CSRF}=token; lumaindex_session=abc`, CSRF)).toBe('token')
    expect(lastCookie(`${CSRF}=token`, CSRF)).toBe('token')
  })

  it('does not match a name that merely ends in the one asked for', () => {
    expect(lastCookie(`other_${CSRF}=neighbour`, CSRF)).toBeNull()
  })

  it('has no value to offer when the cookie is absent', () => {
    expect(lastCookie('', CSRF)).toBeNull()
    expect(lastCookie('lumaindex_session=abc', CSRF)).toBeNull()
  })

  it('decodes a value the browser encoded', () => {
    expect(lastCookie('greeting=a%20b', 'greeting')).toBe('a b')
  })
})
