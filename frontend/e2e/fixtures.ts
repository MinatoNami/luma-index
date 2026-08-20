import { test as base, expect } from '@playwright/test'

/**
 * A signed-in page, with a book to open.
 *
 * The session is minted server-side and handed in by scripts/e2e.sh rather
 * than typed into the login form: these are tests about the reader, and going
 * through a password every time would make them slower and give them a second
 * reason to fail.
 */
export const test = base.extend<{ bookId: string }>({
  bookId: async ({}, use) => {
    const id = process.env.LUMA_E2E_BOOK_ID
    if (!id) throw new Error('LUMA_E2E_BOOK_ID is not set — run via scripts/e2e.sh')
    await use(id)
  },

  page: async ({ page, baseURL }, use) => {
    const session = process.env.LUMA_E2E_SESSION
    if (!session) throw new Error('LUMA_E2E_SESSION is not set — run via scripts/e2e.sh')
    const { hostname } = new URL(baseURL!)
    await page.context().addCookies([
      { name: 'lumaindex_session', value: session, domain: hostname, path: '/' },
    ])
    await use(page)
  },
})

export { expect }
