import { expect, test } from './fixtures'

/**
 * Each of these covers something that has actually gone wrong here, and that
 * no unit test in this repo could have caught.
 */

/** A canvas the browser has genuinely painted, rather than one merely sized. */
async function paintedCanvases(page: import('@playwright/test').Page) {
  return await page.evaluate(() => {
    const canvases = [...document.querySelectorAll('.page canvas')]
    // An unrendered canvas defaults to 300x150; measuring `width > 0` counts
    // placeholders and has produced false "no leak" readings here before.
    return canvases.filter(c => {
      const el = c as HTMLCanvasElement
      return el.width > 300 && el.height > 150
    }).length
  })
}

/**
 * Put the reader in continuous mode, whatever the account was last left in.
 *
 * The reading mode is a saved preference, and the first run of this suite
 * inherited `single` from a session months of commits ago. In single mode one
 * page is laid out, so nothing scrolls — which silently turned three tests
 * into assertions about a reader that cannot move. A test that reads the
 * user's preferences has to set them.
 *
 * The button's title names what it will do, so it says which mode we are in.
 */
async function ensureContinuous(page: import('@playwright/test').Page) {
  const toggle = page.locator('.mode-toggle')
  await expect(toggle).toBeVisible()
  if ((await toggle.getAttribute('title')) === 'Continuous scroll') {
    await toggle.click()
    await page.waitForTimeout(800)
  }
  await expect(toggle).toHaveAttribute('title', 'Single page')
}

/** How far the page area can actually scroll. Zero means there is no test. */
async function scrollableBy(page: import('@playwright/test').Page) {
  return await page.locator('.viewport').evaluate(el => el.scrollHeight - el.clientHeight)
}

test.beforeEach(async ({ page, bookId }) => {
  await page.goto(`/books/${bookId}`)
  await expect(page.locator('.viewport')).toBeVisible()
  // Mode first, then wait for the render. Switching modes throws the canvases
  // away and starts again, so waiting before the switch proves nothing about
  // what the test is about to look at.
  await ensureContinuous(page)
  await expect.poll(() => paintedCanvases(page), { timeout: 60_000 }).toBeGreaterThan(0)
})

/**
 * NOT YET RELIABLE — marked `fixme` deliberately rather than left red.
 *
 * These four are timing-fragile against a real PDF renderer. `paintedCanvases`
 * infers "rendered" from canvas dimensions, which is a proxy: PDF.js resizes a
 * canvas before it awaits its render task, so the count moves before there is
 * anything on screen and moves again when a mode change discards it. Polling
 * that proxy produced a suite that passed, then failed, then skipped, with no
 * change to the application in between.
 *
 * The fix is to wait on the reader rather than on the DOM — it already knows
 * when a page finished painting, and could say so. That is a change to the
 * component's public surface and wants doing deliberately, not while chasing a
 * red test.
 *
 * The two tests above this line do pass consistently, and the harness they run
 * in is the valuable part: real Chromium, real rAF, the one environment where
 * these bugs live.
 */
test('renders a page onto a canvas', async ({ page }) => {
  const painted = await paintedCanvases(page)
  expect(painted).toBeGreaterThan(0)

  // And the canvas is not blank: something was drawn into it.
  const hasInk = await page.evaluate(() => {
    const c = document.querySelector('.page canvas') as HTMLCanvasElement | null
    if (!c) return false
    const ctx = c.getContext('2d')
    if (!ctx) return false
    const { data } = ctx.getImageData(0, 0, Math.min(c.width, 200), Math.min(c.height, 200))
    // A white page is still ink against a transparent canvas.
    return data.some(v => v !== 0)
  })
  expect(hasInk, 'the first page should have been drawn, not just sized').toBe(true)
})

test('keeps a bounded number of canvases while scrolling the whole book', async ({ page }) => {
  // The leak: 82 canvases and 468 MB, because detached elements were never
  // released. The window is a handful of pages either side of the visible one.
  const room = await scrollableBy(page)
  test.skip(room < 500, `this book only scrolls ${room}px — nothing to leak`)

  const viewport = page.locator('.viewport')
  for (const fraction of [0.1, 0.25, 0.5, 0.75, 0.95]) {
    await viewport.evaluate((el, f) => { el.scrollTop = el.scrollHeight * (f as number) }, fraction)
    await page.waitForTimeout(1200)
  }
  const painted = await paintedCanvases(page)
  expect(painted, `canvases painted after scrolling the book: ${painted}`).toBeLessThanOrEqual(12)
})

/**
 * Bring the toolbar back before clicking anything on it.
 *
 * Opening a book restores saved reading progress, which scrolls the viewport,
 * which hides the bar — so a test that clicks a toolbar button straight after
 * load is clicking at a point PDF.js's .textLayer now owns, and Playwright
 * fails it as "intercepts pointer events" rather than as anything to do with
 * the button.
 */
async function revealToolbar(page: import('@playwright/test').Page) {
  const viewport = page.locator('.viewport')
  await viewport.evaluate((el) => { el.scrollTop = Math.max(0, el.scrollTop - 400) })
  await page.waitForTimeout(200)
  await viewport.evaluate((el) => { el.scrollTop = 0 })
  await expect(page.locator('.bar')).not.toHaveClass(/hidden/)
}

test('single-page mode still shows a page after using the arrows', async ({ page }) => {
  // This went blank: the render was kicked off before Vue had created the
  // replacement element, and a stale entry made the page unrenderable for good.
  await revealToolbar(page)
  await page.locator('.mode-toggle').click()
  await expect(page.locator('.mode-toggle')).toHaveAttribute('title', 'Continuous scroll')
  await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)

  const next = page.getByTitle('Next page')
  for (let i = 0; i < 3; i++) {
    await next.click()
    await page.waitForTimeout(900)
    expect(await paintedCanvases(page), `blank after ${i + 1} page turn(s)`).toBeGreaterThan(0)
  }
})

test('the toolbar gets out of the way and comes back', async ({ page }) => {
  const room = await scrollableBy(page)
  test.skip(room < 1000, `this book only scrolls ${room}px — the bar has nowhere to hide`)

  const bar = page.locator('.bar')
  const viewport = page.locator('.viewport')

  await viewport.evaluate(el => { el.scrollTop = 0 })
  await expect(bar).not.toHaveClass(/hidden/)

  // Relative, and in two steps: an absolute target the reader is already at
  // fires no scroll event, which is exactly how this test first fooled itself.
  await viewport.evaluate(el => { el.scrollTop = el.scrollTop + 600 })
  await page.waitForTimeout(300)
  await viewport.evaluate(el => { el.scrollTop = el.scrollTop + 600 })
  await expect(bar).toHaveClass(/hidden/)
  // Collapsed to nothing: no padding box, so its contents cannot be painted
  // inside it — the bug where the bar appeared sliced in half.
  expect(await bar.evaluate(el => el.clientHeight)).toBe(0)

  await viewport.evaluate(el => { el.scrollTop = el.scrollTop - 400 })
  await expect(bar).not.toHaveClass(/hidden/)
})

test('search finds text in the book', async ({ page, bookId }) => {
  const scanned = await page.evaluate(async (id) => {
    const r = await fetch(`/api/library/books/${id}/`, { credentials: 'include' })
    return (await r.json()).has_text_layer === false
  }, bookId)
  test.skip(scanned, 'this book has no text layer, so there is nothing to find')

  await revealToolbar(page)
  await page.getByTitle(/find in book/i).click()
  const input = page.getByPlaceholder(/find in book/i)
  await input.fill('the')
  await expect(page.locator('.findbar .count')).toContainText(/\d+\s*\/\s*\d+|no matches/i, {
    timeout: 45_000,
  })
})

test('the page area can be scrolled from the keyboard', async ({ page }) => {
  // It was focusable by nothing: every button reachable by Tab, and no way to
  // move the page.
  const room = await scrollableBy(page)
  test.skip(room < 200, `this book only scrolls ${room}px — nothing to move`)

  const viewport = page.locator('.viewport')
  await viewport.focus()
  const before = await viewport.evaluate(el => el.scrollTop)
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.waitForTimeout(400)
  const after = await viewport.evaluate(el => el.scrollTop)
  expect(after, 'arrow keys should scroll the focused page area').toBeGreaterThan(before)
})

test('the page being read when the tab closes is the one saved', async ({ page, bookId }) => {
  // Positions are saved on a four-second debounce, and the write meant to
  // catch the last few seconds as a tab closes was a sendBeacon: a POST, with
  // no CSRF header, to an endpoint that only takes PUT. It was refused every
  // time, so closing the tab straight after turning a page lost the page.
  const room = await scrollableBy(page)
  test.skip(room < 500, `this book only scrolls ${room}px — nowhere to move to`)

  // Every ordinary save, so the test can show it was not one of these that
  // carried the new page.
  const saved: number[] = []
  page.on('request', (request) => {
    if (request.method() === 'PUT' && request.url().endsWith(`/books/${bookId}/progress`)) {
      saved.push(JSON.parse(request.postData() ?? '{}').page)
    }
  })

  // Let any save already scheduled by opening the book land first.
  await page.waitForTimeout(4_500)

  const jump = page.getByLabel('Jump to page')
  const before = await jump.getAttribute('placeholder')
  const viewport = page.locator('.viewport')
  const at = await viewport.evaluate(el => el.scrollTop / el.scrollHeight)
  await viewport.evaluate((el, f) => { el.scrollTop = el.scrollHeight * f }, at > 0.5 ? 0.2 : 0.7)
  const movedAt = Date.now()
  await expect(jump).not.toHaveAttribute('placeholder', before ?? '')
  await page.waitForTimeout(300)
  const reading = Number(await jump.getAttribute('placeholder'))

  expect(Date.now() - movedAt, 'too slow to close inside the debounce — this proves nothing')
    .toBeLessThan(3_500)
  expect(saved, 'an ordinary save already carried the new page').not.toContain(reading - 1)

  const context = page.context()
  await page.close()

  await expect.poll(async () => {
    const response = await context.request.get(`/api/library/books/${bookId}/progress`)
    return (await response.json()).page
  }, { timeout: 10_000 }).toBe(reading - 1)
})


/**
 * The canvas of the page in the middle of the viewport, and where we are.
 *
 * Deliberately not "the first canvas carrying pixels": the reader opens at the
 * saved position, and the pages it painted on the way there can keep a sized
 * canvas without being part of the live window. Measuring one of those makes a
 * zoom look like it did nothing.
 */
async function zoomState(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.viewport') as HTMLElement | null
    if (!viewport) return null
    const box = viewport.getBoundingClientRect()
    const middle = box.top + box.height / 2

    const host = [...document.querySelectorAll('.page')].find((el) => {
      const r = el.getBoundingClientRect()
      return r.top <= middle && r.bottom >= middle
    })
    const canvas = host?.querySelector('canvas') as HTMLCanvasElement | null
    if (!canvas || canvas.width <= 300) return null
    return {
      cssWidth: Math.round(canvas.getBoundingClientRect().width),
      backing: canvas.width,
      scrollTop: Math.round(viewport.scrollTop),
    }
  })
}

test('zooming never blanks the page', async ({ page }) => {
  // Each zoom step used to release every canvas and re-render from nothing, so
  // the page went blank and came back. The old pixels are stretched now while
  // the sharp render happens behind them.
  await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)

  const before = await zoomState(page)
  expect(before).not.toBeNull()

  await revealToolbar(page)
  await page.getByRole('button', { name: /more reader controls/i }).click()
  await page.getByRole('menuitem', { name: /^zoom in$/i }).click()

  // Immediately: the canvas must still be carrying pixels, and must already be
  // wider on screen — that is the stretch standing in for the new render.
  const during = await zoomState(page)
  expect(during, 'the canvas was torn down during the zoom').not.toBeNull()
  expect(during!.backing, 'the backing store was zeroed mid-zoom').toBeGreaterThan(300)
  expect(during!.cssWidth, 'the page did not grow on screen').toBeGreaterThan(before!.cssWidth)

  // And it still ends up sharp: the backing store grows once the render lands.
  await expect.poll(async () => (await zoomState(page))?.backing ?? 0, { timeout: 30_000 })
    .toBeGreaterThan(before!.backing)
})



test('a trackpad zoom scales the page and holds its place', async ({ page }) => {
  await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)
  await ensureContinuous(page)
  // Somewhere down the book, so an anchored zoom has a scroll position to keep.
  await page.locator('.viewport').evaluate(el => { el.scrollTop = 400 })
  await page.waitForTimeout(300)

  const before = await zoomState(page)
  expect(before).not.toBeNull()

  // ctrl+wheel is how a trackpad pinch reaches the page.
  await page.locator('.viewport').hover()
  await page.keyboard.down('Control')
  await page.mouse.wheel(0, -240)
  await page.keyboard.up('Control')
  await page.waitForTimeout(200)

  const after = await zoomState(page)
  expect(after!.cssWidth, 'ctrl+wheel did not zoom').toBeGreaterThan(before!.cssWidth)
  // Anchored, not reset: zooming in below the top must not send you back to it.
  expect(after!.scrollTop, 'the zoom threw away the scroll position').toBeGreaterThan(100)

  // And the page must still be sharp afterwards, not a stretched old bitmap.
  await expect.poll(async () => (await zoomState(page))!.backing, { timeout: 30_000 })
    .toBeGreaterThan(before!.backing)
})

test('two fingers zoom the page', async ({ page }) => {
  await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)
  const before = await zoomState(page)
  expect(before).not.toBeNull()

  // Playwright's touchscreen is one finger. A pinch has to be dispatched.
  const spread = (from: number, to: number, type: string) => page.evaluate(
    ({ from, to, type }) => {
      const target = document.querySelector('.viewport') as HTMLElement
      const box = target.getBoundingClientRect()
      const midX = box.left + box.width / 2
      const midY = box.top + box.height / 2
      const at = (dx: number) => new Touch({
        identifier: dx, target,
        clientX: midX + dx, clientY: midY,
        pageX: midX + dx, pageY: midY,
      })
      const touches = [at(-from / 2), at(to / 2)]
      target.dispatchEvent(new TouchEvent(type, {
        touches, targetTouches: touches, changedTouches: touches,
        bubbles: true, cancelable: true,
      }))
    },
    { from, to, type },
  )

  await spread(100, 100, 'touchstart')
  await spread(100, 200, 'touchmove')

  // Mid-gesture the column is transformed rather than re-rendered — that is
  // what makes a pinch smooth instead of a slideshow of canvases.
  const transform = await page.locator('.pages').evaluate(el => el.style.transform)
  expect(transform, 'the pinch did not scale anything').toMatch(/scale\(/)

  await page.evaluate(() => {
    const target = document.querySelector('.viewport') as HTMLElement
    target.dispatchEvent(new TouchEvent('touchend', {
      touches: [], targetTouches: [], changedTouches: [],
      bubbles: true, cancelable: true,
    }))
  })
  await page.waitForTimeout(300)

  // On release the transform goes and the real size takes over.
  expect(await page.locator('.pages').evaluate(el => el.style.transform)).toBe('')
  const after = await zoomState(page)
  expect(after!.cssWidth, 'the pinch did not commit').toBeGreaterThan(before!.cssWidth)
})


/**
 * At three device pixels per CSS pixel, which is what a modern phone has.
 *
 * The default here is 1×, where "up to 2" and "up to 3" are the same number and
 * these two would pass without testing anything.
 */
test.describe('on a high-resolution screen', () => {
  test.use({ deviceScaleFactor: 3 })

  test('the page being read is rendered sharper than its neighbours', async ({ page }) => {
    // The reader used to cap every page at two device pixels per CSS pixel, so a
    // 3× screen gave back a third of its resolution on the one page in front of
    // you. The page you settle on is now upgraded; the neighbours kept warm on
    // either side are not, because they are what add up.
    await ensureContinuous(page)
    await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)

    // Density per CSS pixel, per page, for everything currently carrying pixels.
    const densities = () => page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll('.page')].flatMap((host) => {
        const canvas = host.querySelector('canvas') as HTMLCanvasElement
        const css = Number.parseFloat(canvas?.style.width || '0')
        if (!css || canvas.width <= 300) return []
        const number = Number((host as HTMLElement).dataset.page)
        return [[number, Math.round((canvas.width / css) * 100) / 100]]
      }),
    ))

    // Settle on page one, so there is no doubt which page is the focused one.
    await page.locator('.viewport').evaluate(el => { el.scrollTop = 0 })

    // The upgrade is deliberately not part of the first render — it waits for
    // the scrolling to stop — so this is a poll, not a read.
    //
    // Strictly above the neighbours' cap rather than exactly 3: the budget has
    // the last word, and a browser window is far wider than the phone screens
    // that actually have three device pixels, so a full-width page here costs
    // enough to be shaved a little. On a phone it is not.
    await expect.poll(async () => (await densities())[1] ?? 0, { timeout: 30_000 })
      .toBeGreaterThan(2)

    const all = await densities()
    const neighbours = Object.entries(all)
      .filter(([number]) => Number(number) !== 1)
      .map(([, density]) => density)

    expect(neighbours.length, 'nothing was prefetched to compare against')
      .toBeGreaterThan(0)
    expect(all[1]).toBeLessThanOrEqual(3)
    // The other half of the point: the pages either side stay at two, because
    // they are the ones that add up.
    for (const density of neighbours) expect(density).toBe(2)
  })

  test('a canvas never exceeds what the browser will allocate', async ({ page }) => {
    // Zoomed all the way in, a page at full device resolution is large enough
    // that the browser silently declines to allocate it and paints nothing.
    await ensureContinuous(page)
    await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)

    await revealToolbar(page)
    for (let step = 0; step < 8; step += 1) {
      await page.getByRole('button', { name: /more reader controls/i }).click()
      await page.getByRole('menuitem', { name: /^zoom in$/i }).click()
    }
    await page.waitForTimeout(1500)

    const worst = await page.evaluate(() => Math.max(0, ...[...document.querySelectorAll('canvas')]
      .map(c => (c as HTMLCanvasElement).width * (c as HTMLCanvasElement).height)))
    expect(worst, 'nothing was painted at full zoom').toBeGreaterThan(0)
    expect(worst, 'a canvas went past the allocation budget').toBeLessThanOrEqual(16_777_216)

    // And it is still a page, not a blank rectangle.
    expect(await paintedCanvases(page)).toBeGreaterThan(0)
  })
})
