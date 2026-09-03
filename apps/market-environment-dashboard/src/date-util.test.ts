import { describe, expect, it } from 'vitest'
import { getDefaultMarketDate } from './date-util'

describe('research dashboard default market date', () => {
  it('uses the previous date before 15:00', () => {
    expect(getDefaultMarketDate(new Date(2026, 8, 3, 14, 59, 59))).toBe('2026-09-02')
  })

  it('uses the current date from 15:00', () => {
    expect(getDefaultMarketDate(new Date(2026, 8, 3, 15, 0, 0))).toBe('2026-09-03')
  })

  it('handles the previous month before the cutoff', () => {
    expect(getDefaultMarketDate(new Date(2026, 8, 1, 9, 0, 0))).toBe('2026-08-31')
  })

  it('handles the previous year before the cutoff', () => {
    expect(getDefaultMarketDate(new Date(2026, 0, 1, 9, 0, 0))).toBe('2025-12-31')
  })
})
