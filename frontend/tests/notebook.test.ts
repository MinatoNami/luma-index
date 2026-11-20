import { describe, expect, it } from 'vitest'

import {
  goalPercent, localDate, streakLabel, weekday, weekScale,
} from '~/composables/useNotebook'

/**
 * The client half of reading activity. The one that matters is `localDate`:
 * it decides which day a page counts towards, and the obvious way to write it
 * — `toISOString().slice(0, 10)` — is UTC, which is the wrong day for half the
 * planet for part of every day.
 */
describe('the reader\'s own date', () => {
  it('is the local calendar date, not the UTC one', () => {
    // 00:30 local on 1 March: in any zone east of UTC, toISOString() still
    // says the last day of February.
    const justAfterMidnight = new Date(2026, 2, 1, 0, 30)
    expect(localDate(justAfterMidnight)).toBe('2026-03-01')
  })

  it('pads months and days', () => {
    expect(localDate(new Date(2026, 0, 5, 12))).toBe('2026-01-05')
  })
})

describe('progress towards the daily goal', () => {
  it('is a percentage of the goal, rounded', () => {
    expect(goalPercent(5, 20)).toBe(25)
    expect(goalPercent(1, 3)).toBe(33)
  })

  it('stops at a full bar when the goal is passed', () => {
    expect(goalPercent(45, 20)).toBe(100)
  })

  it('shows nothing when there is no goal', () => {
    expect(goalPercent(12, 0)).toBe(0)
  })
})

describe('the streak, in words', () => {
  it('invites rather than reports a zero', () => {
    expect(streakLabel(0)).toBe('Read today to start a streak')
  })

  it('counts days in a row', () => {
    expect(streakLabel(1)).toBe('1 day in a row')
    expect(streakLabel(12)).toBe('12 days in a row')
  })
})

describe('the week\'s bar heights', () => {
  const week = [3, 0, 10, 5, 0, 0, 2].map(pages => ({ pages }))

  it('scale to the tallest day', () => {
    const heights = weekScale(week, 0)
    expect(Math.max(...heights)).toBe(1)
    expect(heights[0]).toBeCloseTo(0.3)
    expect(heights[1]).toBe(0)
  })

  it('scale to the goal when the goal is higher, so short days look short', () => {
    const heights = weekScale(week, 20)
    expect(heights[2]).toBe(0.5)
  })

  it('do not divide by zero in an empty week', () => {
    expect(weekScale(week.map(() => ({ pages: 0 })), 0)).toEqual([0, 0, 0, 0, 0, 0, 0])
  })
})

describe('the weekday label', () => {
  it('reads a YYYY-MM-DD as a local date, not UTC midnight', () => {
    // new Date('2026-06-15') is UTC midnight, which west of UTC is still the
    // 14th — a Sunday labelled as the Monday it actually was would be wrong
    // for every bar in the chart.
    const expected = new Date(2026, 5, 15).toLocaleDateString(undefined, { weekday: 'short' })
    expect(weekday('2026-06-15')).toBe(expected)
  })
})
