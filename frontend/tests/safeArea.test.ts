import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Something must hold the content off the camera, on every screen.
 *
 * `viewport-fit=cover` means the web view is the whole phone screen, notch and
 * home indicator included, and the app is responsible for the corners. That was
 * true and handled until a redesign moved the top chrome out of the pages and
 * into a layout, and the inset did not come with it: the only declaration left
 * was on `.rail`, which is `display: none` below 60rem. Every page but the
 * reader then drew its first line under the Dynamic Island, and nothing failed
 * — the app looks correct at every width a developer is likely to be sitting
 * in front of.
 *
 * A lint, because that is the shape of the bug: not wrong behaviour, an absent
 * declaration in a file nobody was editing.
 */

const ROOT = process.cwd()
const read = (path: string) => readFileSync(join(ROOT, path), 'utf8')

/** The body of the first `selector { ... }` rule in a stylesheet. */
function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`)
  if (start === -1) return ''
  const end = css.indexOf('}', start)
  return end === -1 ? '' : css.slice(start, end)
}

describe('safe areas', () => {
  it('are held by the app shell, which is present at every width', () => {
    // Not `.rail`, `.topbar` or any other chrome: those come and go with the
    // breakpoint and with the design. `.app` wraps every page in the layout.
    const shell = rule(read('layouts/default.vue'), '.app')
    expect(shell, 'the .app rule is gone or was renamed').not.toBe('')
    expect(shell).toContain('env(safe-area-inset-top)')
    expect(shell).toContain('env(safe-area-inset-left)')
    expect(shell).toContain('env(safe-area-inset-right)')
  })

  it('are held by the reader too, which opts out of the layout', () => {
    // definePageMeta({ layout: false }), so nothing above it can do this for it.
    const shell = rule(read('pages/books/[id]/index.vue'), '.reader-shell')
    expect(shell, 'the .reader-shell rule is gone or was renamed').not.toBe('')
    expect(shell).toContain('env(safe-area-inset-top')
  })

  it('leave the status bar to iOS rather than drawing under it', () => {
    // black-translucent puts the page under the status bar and the clock in
    // white on top of it — unreadable over a light theme, and only safe if
    // every top edge in the app carries the inset. Changing this back means
    // auditing all of them again.
    const config = read('nuxt.config.ts')
    expect(config).toContain("'apple-mobile-web-app-status-bar-style', content: 'default'")
    expect(config).toContain('viewport-fit=cover')
  })
})
