import { describe, expect, it } from 'vitest'

import { nextTheme, type Theme } from '~/composables/useSettings'

/**
 * One property: whichever theme is on screen, the toggle offers the other one.
 *
 * The bug this replaces: the toggle cycled light → dark → system, and `system`
 * on a light machine already looks light — so choosing `light` moved the stored
 * value and changed nothing visible. It took two presses to see anything.
 */
describe('what the theme toggle offers next', () => {
  it('offers dark when an explicit light is showing', () => {
    expect(nextTheme('light', false)).toBe('dark')
    expect(nextTheme('light', true)).toBe('dark')
  })

  it('offers light when an explicit dark is showing', () => {
    expect(nextTheme('dark', false)).toBe('light')
    expect(nextTheme('dark', true)).toBe('light')
  })

  it('follows the machine when the choice is "system"', () => {
    // The case that needed two presses: system on a light machine.
    expect(nextTheme('system', false)).toBe('dark')
    expect(nextTheme('system', true)).toBe('light')
  })

  it('never offers the theme already on screen', () => {
    const showing = (chosen: Theme, dark: boolean) =>
      chosen === 'system' ? (dark ? 'dark' : 'light') : chosen

    for (const chosen of ['system', 'light', 'dark'] as Theme[]) {
      for (const dark of [true, false]) {
        expect(nextTheme(chosen, dark)).not.toBe(showing(chosen, dark))
      }
    }
  })
})
