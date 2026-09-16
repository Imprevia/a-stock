/**
 * Pure date / timezone helpers used by every dashboard view. Phase 1/2 of
 * frontend-router-and-stores centralised timezone state into a Pinia store;
 * `formatDateTime` previously read module-scope reactive state implicitly.
 * It now requires the caller to supply the resolved timezone explicitly so
 * the helper stays pure and is trivial to unit-test.
 *
 * The thin-shell in `timezone.ts` continues to expose
 * `formatDateTime(value)` for legacy call sites — that shell reads the
 * current effective timezone from `usePreferencesStore()`. New code should
 * import from this file and pass the timezone it obtained from the store
 * or a caller-provided default.
 */

export const DEFAULT_TIME_ZONE = 'UTC'

export type DateTimePrecision = 'minute' | 'second' | 'millisecond'

export interface FormatDateTimeOptions {
  precision?: DateTimePrecision
  timeZone?: string
}

export function isSupportedTimeZone(value: string | null | undefined): value is string {
  if (!value || typeof value !== 'string') return false
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value }).format()
    return true
  } catch {
    return false
  }
}

export function getBrowserTimeZone(): string | null {
  try {
    const value = Intl.DateTimeFormat().resolvedOptions().timeZone
    return isSupportedTimeZone(value) ? value : null
  } catch {
    return null
  }
}

export function parseTimestamp(value: string | Date | null | undefined): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value !== 'string' || !value.trim()) return null
  // Require an explicit UTC marker/offset. This prevents an API timestamp
  // without a zone from being silently interpreted in the browser's zone.
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function partsFor(date: Date, timeZone: string, precision: DateTimePrecision) {
  const baseOptions = {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    ...(precision !== 'minute' ? { second: '2-digit' as const } : {}),
    ...(precision === 'millisecond' ? { fractionalSecondDigits: 3 as const } : {}),
    hourCycle: 'h23',
  } as const
  let formatter: Intl.DateTimeFormat
  try {
    formatter = new Intl.DateTimeFormat('en-CA', { ...baseOptions, timeZoneName: 'shortOffset' })
  } catch {
    // Safari versions without `shortOffset` still expose a short zone
    // abbreviation (EST/CST/GMT+8), which is preferable to hiding the time.
    formatter = new Intl.DateTimeFormat('en-CA', { ...baseOptions, timeZoneName: 'short' })
  }
  return Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value])) as Record<string, string>
}

export function formatDateTime(
  value: string | Date | null | undefined,
  options: FormatDateTimeOptions = {},
): string {
  const parsed = parseTimestamp(value)
  if (!parsed) return '--'
  const configuredTimeZone = options.timeZone ?? DEFAULT_TIME_ZONE
  const timeZone = isSupportedTimeZone(configuredTimeZone) ? configuredTimeZone : DEFAULT_TIME_ZONE
  const precision = options.precision ?? 'minute'
  try {
    const parts = partsFor(parsed, timeZone, precision)
    const date = `${parts.year}-${parts.month}-${parts.day}`
    const clock = [parts.hour, parts.minute, parts.second].filter(Boolean).join(':')
    const milliseconds = precision === 'millisecond' && parts.fractionalSecond ? `.${parts.fractionalSecond}` : ''
    const offset = parts.timeZoneName === 'GMT' ? 'UTC' : parts.timeZoneName || timeZone
    return `${date} ${clock}${milliseconds} ${offset}`
  } catch {
    return '--'
  }
}

export function formatDateTimeTitle(value: string | Date | null | undefined): string {
  const parsed = parseTimestamp(value)
  return parsed ? `原始 UTC：${parsed.toISOString()}` : '原始 UTC：不可用'
}

export function getCurrentUtcIso(): string {
  return new Date().toISOString()
}

export function formatDateTimeWithTimeZone(
  value: string | Date | null | undefined,
  timeZone: string,
  options: Omit<FormatDateTimeOptions, 'timeZone'> = {},
): string {
  return formatDateTime(value, { ...options, timeZone })
}

export function formatLocalDate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function getDefaultMarketDate(now: Date): string {
  const DEFAULT_DATE_CUTOFF_HOUR = 15
  const selectedDate = new Date(now)
  if (selectedDate.getHours() < DEFAULT_DATE_CUTOFF_HOUR) {
    selectedDate.setDate(selectedDate.getDate() - 1)
  }
  return formatLocalDate(selectedDate)
}