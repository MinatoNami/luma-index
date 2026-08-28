import { describe, expect, it } from 'vitest'
import { MAX_CANVAS_PIXELS, affordableRatio, clampScale } from '~/composables/usePdf'

describe('clampScale', () => {
  it('keeps a sane zoom inside the range', () => {
    expect(clampScale(1.5)).toBe(1.5)
    expect(clampScale(0.01)).toBe(0.25)
    expect(clampScale(99)).toBe(4)
  })

  it('does not pass a broken number through', () => {
    // A pinch that starts with two fingers in the same place divides by zero,
    // and NaN as a scale renders nothing at all with no error to explain it.
    expect(clampScale(Number.NaN)).toBe(1)
    expect(clampScale(Number.POSITIVE_INFINITY)).toBe(4)
  })
})

describe('affordableRatio', () => {
  // A letter page at 1×, which is what most reading happens at.
  const letter = { width: 612, height: 792 }

  it('gives a normal page every device pixel it asks for', () => {
    expect(affordableRatio(letter.width, letter.height, 3)).toBe(3)
    expect(affordableRatio(letter.width, letter.height, 2)).toBe(2)
  })

  it('never lets one canvas exceed the budget', () => {
    // The size that used to paint nothing: a full-page zoom on a 3× phone.
    const wide = letter.width * 4
    const tall = letter.height * 4
    const ratio = affordableRatio(wide, tall, 3)
    expect(ratio).toBeLessThan(3)
    expect(wide * ratio * tall * ratio).toBeLessThanOrEqual(MAX_CANVAS_PIXELS + 1)
  })

  it('is never asked to divide by nothing', () => {
    expect(affordableRatio(0, 0, 3)).toBe(1)
    expect(affordableRatio(612, 792, Number.NaN)).toBe(1)
  })
})
