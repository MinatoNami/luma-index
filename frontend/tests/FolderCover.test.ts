import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import FolderCover from '~/components/FolderCover.vue'
import type { Folder } from '~/composables/useLibrary'

const folder = (previews: number[]): Folder => ({
  id: 1,
  name: 'Ebooks',
  parent: null,
  path: 'Ebooks',
  has_children: false,
  book_count: previews.length,
  folder_count: 0,
  item_count: previews.length,
  preview_book_ids: previews,
  deleted_at: null,
  expires_at: null,
})

const mountCover = (previews: number[]) =>
  mount(FolderCover, {
    props: { folder: folder(previews) },
    global: { stubs: { AppIcon: true } },
  })

describe('a folder with covers to borrow', () => {
  it('tiles them, in the order the API sent them', () => {
    const w = mountCover([9, 8, 7, 6])

    expect(w.findAll('img').map(i => i.attributes('src'))).toEqual([
      '/api/library/books/9/thumbnail',
      '/api/library/books/8/thumbnail',
      '/api/library/books/7/thumbnail',
      '/api/library/books/6/thumbnail',
    ])
  })

  it('always draws four cells, so a half-full folder reads as half full', () => {
    // Not "as broken": the empty ones show the folder's own tint.
    const w = mountCover([9, 8])

    expect(w.findAll('.tile')).toHaveLength(4)
    expect(w.findAll('img')).toHaveLength(2)
  })

  it('never draws more than four, however many it is given', () => {
    const w = mountCover([1, 2, 3, 4, 5, 6])

    expect(w.findAll('img')).toHaveLength(4)
  })

  it('says it is a folder, since four covers bury the tint', () => {
    expect(mountCover([9]).find('.corner').exists()).toBe(true)
  })

  it('hides the tiles from screen readers — the name is right there', () => {
    expect(mountCover([9]).find('.mosaic').attributes('aria-hidden')).toBe('true')
  })
})

describe('a folder with nothing to borrow', () => {
  it('keeps the plain folder glyph', () => {
    const w = mountCover([])

    expect(w.find('.mosaic').exists()).toBe(false)
    expect(w.classes()).toContain('is-empty')
  })

  it('drops the badge, which would only repeat the glyph underneath it', () => {
    expect(mountCover([]).find('.corner').exists()).toBe(false)
  })
})

describe('a cover that will not load', () => {
  it('drops that tile and closes the gap', async () => {
    const w = mountCover([9, 8, 7])

    await w.findAll('img')[0].trigger('error')
    await nextTick()

    expect(w.findAll('img').map(i => i.attributes('src'))).toEqual([
      '/api/library/books/8/thumbnail',
      '/api/library/books/7/thumbnail',
    ])
  })

  it('falls back to the glyph once every tile has failed', async () => {
    const w = mountCover([9])

    await w.findAll('img')[0].trigger('error')
    await nextTick()

    expect(w.classes()).toContain('is-empty')
  })
})

describe('when the folder contents change', () => {
  it('gives the failed tiles another go', async () => {
    const w = mountCover([9])
    await w.findAll('img')[0].trigger('error')
    await nextTick()
    expect(w.classes()).toContain('is-empty')

    await w.setProps({ folder: folder([9, 8]) })
    await nextTick()

    expect(w.findAll('img')).toHaveLength(2)
  })
})
