import { describe, expect, it } from 'vitest'

import {
  citation, countLabel, defaultOrder, goalPercent, localDate, relativeDay, streakLabel, weekday,
  weekScale,
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

describe('when a note was written', () => {
  const now = new Date(2026, 10, 21, 1, 0)  // 1am on 21 November

  it('counts calendar days, not 24-hour spans', () => {
    // Two hours ago, but before midnight: yesterday, not today.
    expect(relativeDay(new Date(2026, 10, 20, 23, 0).toISOString(), now)).toBe('Yesterday')
    expect(relativeDay(new Date(2026, 10, 21, 0, 30).toISOString(), now)).toBe('Today')
  })

  it('falls back to a date, with the year only when it is not this one', () => {
    const lastWeek = new Date(2026, 10, 12, 9, 0)
    expect(relativeDay(lastWeek.toISOString(), now)).toBe(
      lastWeek.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }))
    const lastYear = new Date(2025, 2, 3, 9, 0)
    expect(relativeDay(lastYear.toISOString(), now)).toContain('2025')
  })
})

describe('the notebook\'s helpers', () => {
  it('reads a book in page order and the whole notebook newest first', () => {
    expect(defaultOrder(9)).toBe('page')
    expect(defaultOrder(null)).toBe('recent')
  })

  it('copies a passage with where it came from', () => {
    expect(citation({ text: ' Simplify, simplify. ', book: { id: 1, title: 'Walden' }, page: 90 }))
      .toBe('“Simplify, simplify.”\n— Walden, page 91')
  })

  it('counts only what there is', () => {
    expect(countLabel(2, 1)).toBe('2 highlights · 1 note')
    expect(countLabel(1, 0)).toBe('1 highlight')
    expect(countLabel(0, 0)).toBe('Nothing yet')
  })
})
