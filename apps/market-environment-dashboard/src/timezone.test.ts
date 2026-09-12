import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  formatDateTime,
  formatDateTimeTitle,
  getBrowserTimeZone,
  isSupportedTimeZone,
  resolveEffectiveTimeZone,
} from './timezone'

describe('timezone formatting', () => {
  afterEach(() => vi.restoreAllMocks())

  it('formats UTC input in the selected zone with an explicit offset', () => {
    expect(formatDateTime('2026-09-12T05:25:50Z', { timeZone: 'Asia/Shanghai', precision: 'minute' }))
      .toBe('2026-09-12 13:25 GMT+8')
    expect(formatDateTimeTitle('2026-09-12T05:25:50Z')).toBe('原始 UTC：2026-09-12T05:25:50.000Z')
  })

  it('handles DST transitions and cross-day offsets', () => {
    expect(formatDateTime('2026-03-08T06:30:00Z', { timeZone: 'America/New_York', precision: 'second' }))
      .toBe('2026-03-08 01:30:00 GMT-5')
    expect(formatDateTime('2026-03-08T07:30:00Z', { timeZone: 'America/New_York', precision: 'second' }))
      .toBe('2026-03-08 03:30:00 GMT-4')
    expect(formatDateTime('2026-09-12T23:59:59.123+08:00', { timeZone: 'America/Los_Angeles', precision: 'millisecond' }))
      .toBe('2026-09-12 08:59:59.123 GMT-7')
  })

  it('returns a safe placeholder for null, invalid, date-only and zone-less values', () => {
    expect(formatDateTime(null)).toBe('--')
    expect(formatDateTime('not-a-date')).toBe('--')
    expect(formatDateTime('2026-09-12')).toBe('--')
    expect(formatDateTime('2026-09-12T05:25:50')).toBe('--')
    expect(formatDateTimeTitle(null)).toBe('原始 UTC：不可用')
  })

  it('resolves personal, workspace, browser and UTC fallback in order', () => {
    expect(resolveEffectiveTimeZone('Asia/Tokyo', 'UTC', 'America/New_York').source).toBe('personal')
    expect(resolveEffectiveTimeZone(null, 'Europe/London', 'America/New_York').timeZone).toBe('Europe/London')
    expect(resolveEffectiveTimeZone(null, null, 'America/New_York').source).toBe('browser')
    expect(resolveEffectiveTimeZone('Not/AZone', 'Europe/London', 'America/New_York')).toMatchObject({ timeZone: 'UTC', source: 'utc-fallback' })
  })

  it('validates IANA identifiers and safely handles browser timezone lookup', () => {
    expect(isSupportedTimeZone('Asia/Shanghai')).toBe(true)
    expect(isSupportedTimeZone('Not/AZone')).toBe(false)
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementationOnce(() => { throw new Error('privacy mode') })
    expect(getBrowserTimeZone()).toBe(null)
  })
})

