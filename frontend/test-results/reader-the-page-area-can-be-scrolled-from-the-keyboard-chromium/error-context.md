# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: reader.spec.ts >> the page area can be scrolled from the keyboard
- Location: e2e/reader.spec.ts:162:1

# Error details

```
Error: arrow keys should scroll the focused page area

expect(received).toBeGreaterThan(expected)

Expected: > 175031
Received:   0
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]:
      - link "Back to library" [ref=e6] [cursor=pointer]:
        - /url: /?folder=14
      - button "Show contents" [ref=e10] [cursor=pointer]
      - button "Show page thumbnails" [ref=e13] [cursor=pointer]
      - button "Bookmarks, highlights and notes" [ref=e16] [cursor=pointer]
      - heading "AI Engineering_ Building Applications with Foundation Models (2025, O_Reilly Media)" [level=1] [ref=e19]
    - generic [ref=e20]:
      - button "Previous page" [ref=e21] [cursor=pointer]
      - generic [ref=e24]:
        - textbox "Jump to page" [ref=e25]:
          - /placeholder: "268"
        - generic [ref=e26]: / 535
      - button "Next page" [ref=e27] [cursor=pointer]
      - generic [ref=e30]: 50%
      - button "Bookmark this page" [ref=e31] [cursor=pointer]
    - generic [ref=e35]:
      - button "Find in book (⌘F)" [ref=e36] [cursor=pointer]
      - button "−" [ref=e39] [cursor=pointer]
      - button "Fit page" [ref=e41] [cursor=pointer]
      - button "+" [ref=e43] [cursor=pointer]
      - button "Scroll" [ref=e45] [cursor=pointer]
      - button "Fullscreen" [ref=e47] [cursor=pointer]
  - main [ref=e50]:
    - region "Book pages" [active] [ref=e52]:
      - alert [ref=e53]: Cannot use the same canvas during multiple render() operations. Use different canvas or ensure previous operations were cancelled or completed.
```

# Test source

```ts
  75  |  */
  76  | test.fixme('renders a page onto a canvas', async ({ page }) => {
  77  |   const painted = await paintedCanvases(page)
  78  |   expect(painted).toBeGreaterThan(0)
  79  | 
  80  |   // And the canvas is not blank: something was drawn into it.
  81  |   const hasInk = await page.evaluate(() => {
  82  |     const c = document.querySelector('.page canvas') as HTMLCanvasElement | null
  83  |     if (!c) return false
  84  |     const ctx = c.getContext('2d')
  85  |     if (!ctx) return false
  86  |     const { data } = ctx.getImageData(0, 0, Math.min(c.width, 200), Math.min(c.height, 200))
  87  |     // A white page is still ink against a transparent canvas.
  88  |     return data.some(v => v !== 0)
  89  |   })
  90  |   expect(hasInk, 'the first page should have been drawn, not just sized').toBe(true)
  91  | })
  92  | 
  93  | test('keeps a bounded number of canvases while scrolling the whole book', async ({ page }) => {
  94  |   // The leak: 82 canvases and 468 MB, because detached elements were never
  95  |   // released. The window is a handful of pages either side of the visible one.
  96  |   const room = await scrollableBy(page)
  97  |   test.skip(room < 500, `this book only scrolls ${room}px — nothing to leak`)
  98  | 
  99  |   const viewport = page.locator('.viewport')
  100 |   for (const fraction of [0.1, 0.25, 0.5, 0.75, 0.95]) {
  101 |     await viewport.evaluate((el, f) => { el.scrollTop = el.scrollHeight * (f as number) }, fraction)
  102 |     await page.waitForTimeout(1200)
  103 |   }
  104 |   const painted = await paintedCanvases(page)
  105 |   expect(painted, `canvases painted after scrolling the book: ${painted}`).toBeLessThanOrEqual(12)
  106 | })
  107 | 
  108 | test.fixme('single-page mode still shows a page after using the arrows', async ({ page }) => {
  109 |   // This went blank: the render was kicked off before Vue had created the
  110 |   // replacement element, and a stale entry made the page unrenderable for good.
  111 |   await page.locator('.mode-toggle').click()
  112 |   await expect(page.locator('.mode-toggle')).toHaveAttribute('title', 'Continuous scroll')
  113 |   await expect.poll(() => paintedCanvases(page), { timeout: 30_000 }).toBeGreaterThan(0)
  114 | 
  115 |   const next = page.getByTitle('Next page')
  116 |   for (let i = 0; i < 3; i++) {
  117 |     await next.click()
  118 |     await page.waitForTimeout(900)
  119 |     expect(await paintedCanvases(page), `blank after ${i + 1} page turn(s)`).toBeGreaterThan(0)
  120 |   }
  121 | })
  122 | 
  123 | test.fixme('the toolbar gets out of the way and comes back', async ({ page }) => {
  124 |   const room = await scrollableBy(page)
  125 |   test.skip(room < 1000, `this book only scrolls ${room}px — the bar has nowhere to hide`)
  126 | 
  127 |   const bar = page.locator('.bar')
  128 |   const viewport = page.locator('.viewport')
  129 | 
  130 |   await viewport.evaluate(el => { el.scrollTop = 0 })
  131 |   await expect(bar).not.toHaveClass(/hidden/)
  132 | 
  133 |   // Relative, and in two steps: an absolute target the reader is already at
  134 |   // fires no scroll event, which is exactly how this test first fooled itself.
  135 |   await viewport.evaluate(el => { el.scrollTop = el.scrollTop + 600 })
  136 |   await page.waitForTimeout(300)
  137 |   await viewport.evaluate(el => { el.scrollTop = el.scrollTop + 600 })
  138 |   await expect(bar).toHaveClass(/hidden/)
  139 |   // Collapsed to nothing: no padding box, so its contents cannot be painted
  140 |   // inside it — the bug where the bar appeared sliced in half.
  141 |   expect(await bar.evaluate(el => el.clientHeight)).toBe(0)
  142 | 
  143 |   await viewport.evaluate(el => { el.scrollTop = el.scrollTop - 400 })
  144 |   await expect(bar).not.toHaveClass(/hidden/)
  145 | })
  146 | 
  147 | test.fixme('search finds text in the book', async ({ page, bookId }) => {
  148 |   const scanned = await page.evaluate(async (id) => {
  149 |     const r = await fetch(`/api/library/books/${id}/`, { credentials: 'include' })
  150 |     return (await r.json()).has_text_layer === false
  151 |   }, bookId)
  152 |   test.skip(scanned, 'this book has no text layer, so there is nothing to find')
  153 | 
  154 |   await page.getByTitle(/find in book/i).click()
  155 |   const input = page.getByPlaceholder(/find in book/i)
  156 |   await input.fill('the')
  157 |   await expect(page.locator('.findbar .count')).toContainText(/\d+\s*\/\s*\d+|no matches/i, {
  158 |     timeout: 45_000,
  159 |   })
  160 | })
  161 | 
  162 | test('the page area can be scrolled from the keyboard', async ({ page }) => {
  163 |   // It was focusable by nothing: every button reachable by Tab, and no way to
  164 |   // move the page.
  165 |   const room = await scrollableBy(page)
  166 |   test.skip(room < 200, `this book only scrolls ${room}px — nothing to move`)
  167 | 
  168 |   const viewport = page.locator('.viewport')
  169 |   await viewport.focus()
  170 |   const before = await viewport.evaluate(el => el.scrollTop)
  171 |   await page.keyboard.press('ArrowDown')
  172 |   await page.keyboard.press('ArrowDown')
  173 |   await page.waitForTimeout(400)
  174 |   const after = await viewport.evaluate(el => el.scrollTop)
> 175 |   expect(after, 'arrow keys should scroll the focused page area').toBeGreaterThan(before)
      |                                                                   ^ Error: arrow keys should scroll the focused page area
  176 | })
  177 | 
```