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
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
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

describe('how far in you are', () => {
  const started = (percentage: number, page = 0) =>
    book({ progress: { page, page_fraction: 0, percentage, last_opened_at: null } })

  it('draws a bar across the cover once a book has been opened', () => {
    const w = mount(BookCover, {
      props: { book: started(33, 30) },
      global: { stubs: { AppIcon: true } },
    })

    const bar = w.find('.progress')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes('aria-valuenow')).toBe('33')
    expect(w.find('.read').attributes('style')).toContain('width: 33%')
  })

  it('says nothing about a book nobody has opened', () => {
    expect(mountCover(book()).find('.progress').exists()).toBe(false)
    expect(mountCover(started(0)).find('.progress').exists()).toBe(false)
  })

  it('keeps a full bar on a finished book, because that is information too', () => {
    const w = mount(BookCover, {
      props: { book: started(100) },
      global: { stubs: { AppIcon: true } },
    })
    expect(w.find('.read').attributes('style')).toContain('width: 100%')
  })

  it('leaves a thumbnail alone: 28px has no room for a bar', () => {
    const w = mount(BookCover, {
      props: { book: started(50), size: 'sm' },
      global: { stubs: { AppIcon: true } },
    })
    expect(w.find('.progress').exists()).toBe(false)
  })

  it('clamps a percentage the server should never send but might', () => {
    const over = mount(BookCover, {
      props: { book: started(140) },
      global: { stubs: { AppIcon: true } },
    })
    expect(over.find('.read').attributes('style')).toContain('width: 100%')

    const under = mount(BookCover, {
      props: { book: started(-10) },
      global: { stubs: { AppIcon: true } },
    })
    expect(under.find('.progress').exists()).toBe(false)
  })
})
