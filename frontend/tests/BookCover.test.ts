import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import BookCover from '~/components/BookCover.vue'
import type { Book } from '~/composables/useLibrary'

const book = (overrides: Partial<Book> = {}): Book => ({
  id: 1,
  title: 'A Book',
  folder: null,
  path: 'A Book',
  page_count: 10,
  has_text_layer: true,
  visibility: 'private',
  thumbnail_path: 'ab/cd/x.webp',
  source: null,
  progress: null,
  is_favourite: false,
  deleted_at: null,
  expires_at: null,
  ...overrides,
})

const mountCover = (b: Book) =>
  mount(BookCover, { props: { book: b }, global: { stubs: { AppIcon: true } } })

/** Make every <img> look like one the browser had already finished loading. */
function pretendImagesAreCached({ decoded }: { decoded: boolean }) {
  vi.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(true)
  vi.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(decoded ? 600 : 0)
}

afterEach(() => vi.restoreAllMocks())

describe('a cover that has not been rendered yet', () => {
  it('shows a placeholder rather than a broken image', () => {
    const w = mountCover(book({ thumbnail_path: '' }))

    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toContain('Preparing')
  })
})

describe('a cover that arrives normally', () => {
  it('is hidden until it loads, then shown', async () => {
    const w = mountCover(book())

    expect(w.find('img').classes()).not.toContain('loaded')
    expect(w.find('.shimmer').exists()).toBe(true)

    await w.find('img').trigger('load')

    expect(w.find('img').classes()).toContain('loaded')
    expect(w.find('.shimmer').exists()).toBe(false)
  })

  it('falls back to the placeholder when it will not decode', async () => {
    const w = mountCover(book())

    await w.find('img').trigger('error')

    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toContain('No preview')
  })
})

describe('a cover the browser had already finished loading', () => {
  it('is shown even though the load event never fires', async () => {
    // The bug this component has been fixed for twice. On a refresh the markup
    // is server-rendered and a cached cover finishes before hydration attaches
    // @load, so that event is never seen — and the image sat at opacity 0
    // under a shimmer that ran for ever.
    pretendImagesAreCached({ decoded: true })

    const w = mountCover(book())
    await nextTick()

    expect(w.find('img').classes()).toContain('loaded')
    expect(w.find('.shimmer').exists()).toBe(false)
  })

  it('shows the placeholder when it completed without decoding', async () => {
    pretendImagesAreCached({ decoded: false })

    const w = mountCover(book())
    await nextTick()

    expect(w.text()).toContain('No preview')
  })
})

describe('a cover that never arrives', () => {
  it('stops claiming to be loading', async () => {
    // A shimmer that never resolves is a lie: it says "still coming" for ever.
    vi.useFakeTimers()
    const w = mountCover(book())
    expect(w.find('.shimmer').exists()).toBe(true)

    vi.advanceTimersByTime(8000)
    await nextTick()

    expect(w.find('.shimmer').exists()).toBe(false)
    expect(w.text()).toContain('No preview')
    vi.useRealTimers()
  })

  it('does not give up on one that did arrive', async () => {
    vi.useFakeTimers()
    const w = mountCover(book())

    await w.find('img').trigger('load')
    vi.advanceTimersByTime(20_000)
    await nextTick()

    expect(w.find('img').classes()).toContain('loaded')
    vi.useRealTimers()
  })
})

describe('when the cover is replaced', () => {
  it('goes back to loading rather than showing the old one', async () => {
    const w = mountCover(book())
    await w.find('img').trigger('load')

    await w.setProps({ book: book({ thumbnail_path: 'ef/gh/new.webp' }) })
    await nextTick()

    expect(w.find('img').classes()).not.toContain('loaded')
  })
})
