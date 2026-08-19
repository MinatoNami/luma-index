import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SortMenu, { type SortKey } from '~/components/SortMenu.vue'

const mountMenu = (props: Partial<{ modelValue: SortKey; descending: boolean
                                    allowTrashed: boolean }> = {}) =>
  mount(SortMenu, {
    props: { modelValue: 'name', descending: false, ...props },
    global: { stubs: { AppIcon: true } },
  })

const values = (w: ReturnType<typeof mountMenu>) =>
  w.findAll('option').map(o => o.attributes('value'))

describe('what can be sorted by', () => {
  it('offers the columns every listing has', () => {
    expect(values(mountMenu())).toEqual(['name', 'added', 'modified', 'size', 'type'])
  })

  it('keeps "date deleted" out of the library, which has no such column', () => {
    expect(values(mountMenu())).not.toContain('trashed')
  })

  it('offers it first in the trash, where it is the default', () => {
    expect(values(mountMenu({ allowTrashed: true }))[0]).toBe('trashed')
  })
})

describe('the direction control', () => {
  it('describes the order in words that suit the column', () => {
    // "A to Z" on a date column is the kind of label that makes people pick
    // the wrong one.
    expect(mountMenu({ modelValue: 'name' }).find('.direction').attributes('title'))
      .toBe('A to Z')
    expect(mountMenu({ modelValue: 'added' }).find('.direction').attributes('title'))
      .toBe('Oldest first')
    expect(mountMenu({ modelValue: 'size' }).find('.direction').attributes('title'))
      .toBe('Smallest first')
    expect(mountMenu({ modelValue: 'type' }).find('.direction').attributes('title'))
      .toBe('Folders first')
  })

  it('flips those words with the direction', () => {
    expect(mountMenu({ modelValue: 'type', descending: true })
      .find('.direction').attributes('title')).toBe('Files first')
  })

  it('names the action, not the state, for anyone who cannot see the arrow', () => {
    // A button labelled with the order it is already in reads as an
    // instruction: "A to Z" on the control that switches to Z-to-A.
    const w = mountMenu({ modelValue: 'name', descending: false })

    expect(w.find('.direction').attributes('aria-label'))
      .toBe('Reverse sort order (currently A to Z)')
  })

  it('reports which way it is pointing', () => {
    expect(mountMenu({ descending: true }).find('.direction').attributes('aria-pressed'))
      .toBe('true')
    expect(mountMenu({ descending: false }).find('.direction').attributes('aria-pressed'))
      .toBe('false')
  })
})

describe('changing the sort', () => {
  it('asks for the new column', async () => {
    const w = mountMenu()

    await w.find('select').setValue('added')

    expect(w.emitted('update:modelValue')).toEqual([['added']])
  })

  it('asks to reverse, and leaves the column alone', async () => {
    const w = mountMenu({ modelValue: 'size', descending: false })

    await w.find('.direction').trigger('click')

    expect(w.emitted('update:descending')).toEqual([[true]])
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})
