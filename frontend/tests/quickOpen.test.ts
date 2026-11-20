import { describe, expect, it } from 'vitest'

import {
  isQuickOpen, matchPlaces, PLACES, shortcutLabel, splitMatch, step,
} from '~/composables/useQuickOpen'

describe('matching places to what was typed', () => {
  const labels = (q: string) => matchPlaces(q).map(p => p.label)

  it('puts a label that starts with the text first', () => {
    // "no" is also inside "Reading now"; the place called "No…" is the one meant.
    expect(labels('no')[0]).toBe('Notebook')
    expect(labels('no')).toContain('Reading now')
  })

  it('finds a place by another word for it', () => {
    expect(labels('highl')).toEqual(['Notebook'])
    expect(labels('goal')).toEqual(['Settings'])
  })

  it('ignores case and surrounding space', () => {
    expect(labels('  TRASH ')).toEqual(['Trash'])
  })

  it('matches nothing when nothing is typed', () => {
    expect(matchPlaces('')).toEqual([])
    expect(matchPlaces('   ')).toEqual([])
  })

  it('offers every section the rail does, and the notebook', () => {
    const tos = PLACES.map(p => p.to)
    for (const to of ['/', '/library', '/notebook', '/collections', '/shared', '/trash',
      '/settings']) {
      expect(tos).toContain(to)
    }
  })
})

describe('moving through the results with the arrow keys', () => {
  it('moves one at a time', () => {
    expect(step(0, 1, 5)).toBe(1)
    expect(step(3, -1, 5)).toBe(2)
  })

  it('wraps at both ends', () => {
    expect(step(4, 1, 5)).toBe(0)
    expect(step(0, -1, 5)).toBe(4)
  })

  it('has nowhere to go in an empty list', () => {
    expect(step(0, 1, 0)).toBe(-1)
  })

  it('starts from the right end when nothing is highlighted', () => {
    expect(step(-1, 1, 3)).toBe(0)
    expect(step(-1, -1, 3)).toBe(2)
  })
})

describe('the shortcut', () => {
  const key = (k: string, mods: Partial<Record<'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey',
    boolean>> = {}) => ({ key: k, metaKey: false, ctrlKey: false, altKey: false,
    shiftKey: false, ...mods })

  it('is Cmd-K or Ctrl-K', () => {
    expect(isQuickOpen(key('k', { metaKey: true }))).toBe(true)
    expect(isQuickOpen(key('k', { ctrlKey: true }))).toBe(true)
    expect(isQuickOpen(key('K', { metaKey: true }))).toBe(true)
  })

  it('is not a bare K, or K with another modifier', () => {
    expect(isQuickOpen(key('k'))).toBe(false)
    expect(isQuickOpen(key('k', { metaKey: true, shiftKey: true }))).toBe(false)
    expect(isQuickOpen(key('k', { ctrlKey: true, altKey: true }))).toBe(false)
  })

  it('is spelled the way the machine spells it', () => {
    expect(shortcutLabel('MacIntel')).toBe('⌘K')
    expect(shortcutLabel('iPhone')).toBe('⌘K')
    expect(shortcutLabel('Win32')).toBe('Ctrl K')
    expect(shortcutLabel('Linux x86_64')).toBe('Ctrl K')
  })
})

describe('marking what was typed in a result', () => {
  it('splits the label around the first match, ignoring case', () => {
    expect(splitMatch('Walden — Thoreau', 'wal')).toEqual([
      { text: 'Wal', match: true },
      { text: 'den — Thoreau', match: false },
    ])
    expect(splitMatch('The Time Machine', 'time')).toEqual([
      { text: 'The ', match: false },
      { text: 'Time', match: true },
      { text: ' Machine', match: false },
    ])
  })

  it('leaves the label whole when the text is not in it', () => {
    // A place found by an alias: "highl" finds Notebook without appearing in it.
    expect(splitMatch('Notebook', 'highl')).toEqual([{ text: 'Notebook', match: false }])
    expect(splitMatch('Notebook', '  ')).toEqual([{ text: 'Notebook', match: false }])
  })
})
