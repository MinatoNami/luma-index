// Captures the README screenshots. Driven by scripts/screenshots.sh, which
// mints the session and puts this on the compose network.
//
// Library views only, deliberately. A reader screenshot needs a painted PDF.js
// canvas, and PDF.js sizes a canvas before it awaits the render, so "the
// element exists" and "the element has been painted" are different moments —
// the same thing that has four e2e reader tests parked as fixme. Waiting on
// the reader itself is the fix, and it changes the component's public surface.
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL ?? 'http://caddy:8080'
const SESSION = process.env.SESSION
const OUT = process.env.OUT ?? '/out'

const cookie = () => ([{
  name: 'lumaindex_session', value: SESSION,
  domain: new URL(BASE).hostname, path: '/',
}])

/** Resolves once every <img> has decoded, then past the grid's fade-in. */
async function imagesSettled(page, budget = 15000) {
  await page.evaluate(async (ms) => {
    document.querySelectorAll('img[loading="lazy"]').forEach((i) => { i.loading = 'eager' })
    const deadline = Date.now() + ms
    let seen = 0
    while (Date.now() < deadline) {
      const imgs = [...document.querySelectorAll('img')]
      seen = Math.max(seen, imgs.length)
      if (seen && imgs.length >= seen && imgs.every((i) => i.complete && i.naturalWidth > 0)) return
      await new Promise((r) => setTimeout(r, 150))
    }
  }, budget)
  await page.waitForTimeout(900)
}

async function clickIfPresent(page, name) {
  const b = page.getByRole('button', { name, exact: true })
  if (await b.count()) { await b.first().click(); return true }
  return false
}

/** Content height in CSS pixels, so a shot is not mostly empty page. */
async function contentHeight(page, pad = 28) {
  return page.evaluate((p) => {
    // The page's own content box, not a guess from card class names — one
    // page's ".progress-card" is not the last thing on it, and cropping to it
    // cut the shot off a third of the way down.
    const main = document.querySelector('main') ?? document.body
    const bottom = main.getBoundingClientRect().top + main.scrollHeight
    return Math.ceil(Math.min(window.innerHeight, bottom + p))
  }, pad)
}

async function themeApplied(page) {
  await page.waitForFunction(
    () => document.documentElement.getAttribute('data-theme') !== null,
    null, { timeout: 15000 },
  ).catch(() => {})
  await page.waitForTimeout(400)
}

async function shot(page, name, width) {
  const height = await contentHeight(page)
  await page.screenshot({ path: `${OUT}/${name}.png`, clip: { x: 0, y: 0, width, height } })
  console.log(`  wrote ${name}.png  (${width}x${height} css px)`)
}

// Theme lives in UserSettings, server-side, so every context shares it. Dark
// shots have to be taken before the theme is switched, not after.
const browser = await chromium.launch()

const desktop = await browser.newContext({
  viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'dark',
})
await desktop.addCookies(cookie())
const page = await desktop.newPage()
// The landing page: where you were, not what you have.
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await themeApplied(page)
await imagesSettled(page)
await shot(page, 'home', 1440)

await page.goto(`${BASE}/library`, { waitUntil: 'networkidle' })
await themeApplied(page)
await clickIfPresent(page, 'Grid')
await imagesSettled(page)
await shot(page, 'library', 1440)

// The reader, with a page actually painted.
await page.goto(`${BASE}/books/${process.env.BOOK_ID}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(3500)
// Opening a book restores where you were, which scrolls, which hides the bar.
// Photographing the chrome means putting it back first.
await page.locator('.viewport').evaluate((el) => { el.scrollTop = 0 })
await page.waitForTimeout(900)
await page.screenshot({ path: `${OUT}/reader.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } })
console.log('  wrote reader.png')

// One book on a page of its own.
await page.goto(`${BASE}/books/${process.env.BOOK_ID}/details`, { waitUntil: 'networkidle' })
await themeApplied(page)
await imagesSettled(page)
await shot(page, 'book-detail', 1440)

// The phone, which is where the layout was actually settled. Still dark.
const phone = await browser.newContext({
  viewport: { width: 390, height: 1180 }, deviceScaleFactor: 3,
  isMobile: true, hasTouch: true, colorScheme: 'dark',
})
await phone.addCookies(cookie())
const small = await phone.newPage()
await small.goto(`${BASE}/library`, { waitUntil: 'networkidle' })
await themeApplied(small)
await clickIfPresent(small, 'Grid')
await imagesSettled(small)
// The full viewport, not the content box: the tab bar is sticky to the
// bottom of the window, so cropping to content height leaves it out of frame —
// and it is the whole point of the phone layout.
await small.screenshot({ path: `${OUT}/phone.png`, clip: { x: 0, y: 0, width: 390, height: 844 } })
console.log('  wrote phone.png (390x844, full viewport)')
await phone.close()

await browser.close()
