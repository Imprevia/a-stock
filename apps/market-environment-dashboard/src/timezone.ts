import { reactive } from 'vue'

export type TimezonePreferenceSource = 'personal' | 'workspace' | 'browser' | 'utc-fallback'
export type TimezoneSaveScope = 'personal' | 'workspace'

export interface TimezoneResolution {
  timeZone: string
  source: TimezonePreferenceSource
  warning: string | null
}

export interface TimezonePreferencesResponse {
  personalTimeZone?: string | null
  workspaceTimeZone?: string | null
  effectiveTimeZone?: string | null
  canManageWorkspaceTimeZone?: boolean
}

export interface TimezonePreferencesState {
  personalTimeZone: string | null
  workspaceTimeZone: string | null
  effectiveTimeZone: string
  source: TimezonePreferenceSource
  warning: string | null
  loading: boolean
  saving: boolean
  canManageWorkspaceTimeZone: boolean
  backendAvailable: boolean | null
}

const TIMEZONE_ENDPOINT = '/api/preferences/timezone'
const LOCAL_STORAGE_KEY = 'a-stock.personal-time-zone'
const DEFAULT_TIMEZONE = 'UTC'
let preferenceRevision = 0

/**
 * The browser can expose an invalid/empty value in privacy-restricted
 * environments. Keep this check in one place so every caller gets the same
 * safe behavior.
 */
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

export function resolveEffectiveTimeZone(
  personalTimeZone: string | null | undefined,
  workspaceTimeZone: string | null | undefined,
  browserTimeZone: string | null | undefined = getBrowserTimeZone(),
): TimezoneResolution {
  if (personalTimeZone) {
    if (isSupportedTimeZone(personalTimeZone)) return { timeZone: personalTimeZone, source: 'personal', warning: null }
    return { timeZone: DEFAULT_TIMEZONE, source: 'utc-fallback', warning: '个人偏好不是受支持的 IANA 时区，已回退 UTC。' }
  }
  if (workspaceTimeZone) {
    if (isSupportedTimeZone(workspaceTimeZone)) return { timeZone: workspaceTimeZone, source: 'workspace', warning: null }
    return { timeZone: DEFAULT_TIMEZONE, source: 'utc-fallback', warning: '工作区偏好不是受支持的 IANA 时区，已回退 UTC。' }
  }
  if (browserTimeZone && isSupportedTimeZone(browserTimeZone)) return { timeZone: browserTimeZone, source: 'browser', warning: null }
  return { timeZone: DEFAULT_TIMEZONE, source: 'utc-fallback', warning: '无法读取受支持的浏览器时区，已回退 UTC。' }
}

function readLocalPersonalTimeZone() {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(LOCAL_STORAGE_KEY)
    return value || null
  } catch {
    return null
  }
}

function writeLocalPersonalTimeZone(value: string | null) {
  if (typeof window === 'undefined') return
  try {
    if (value) window.localStorage.setItem(LOCAL_STORAGE_KEY, value)
    else window.localStorage.removeItem(LOCAL_STORAGE_KEY)
  } catch {
    // Private browsing/storage-disabled mode is handled by the caller's
    // visible status; the in-memory preference still works for this session.
  }
}

function normaliseResponse(payload: unknown): TimezonePreferencesResponse {
  if (!payload || typeof payload !== 'object') return {}
  const value = payload as Record<string, unknown>
  const personalObject = value.personal && typeof value.personal === 'object' ? value.personal as Record<string, unknown> : null
  const workspaceObject = value.workspace && typeof value.workspace === 'object' ? value.workspace as Record<string, unknown> : null
  const personal = value.personalTimeZone ?? value.personalTimezone ?? value.personal_timezone ?? personalObject?.timeZone ?? personalObject?.timezone ?? value.personal ?? value.timeZone ?? value.timezone
  const workspace = value.workspaceTimeZone ?? value.workspaceTimezone ?? value.workspace_timezone ?? workspaceObject?.timeZone ?? workspaceObject?.timezone ?? value.workspace
  const effective = value.effectiveTimeZone ?? value.effectiveTimezone ?? value.effective_timezone ?? value.effective ?? value.timeZone ?? value.timezone
  const canManage = value.canManageWorkspaceTimeZone ?? value.can_manage_workspace_timezone
  return {
    personalTimeZone: typeof personal === 'string' ? personal : personal === null ? null : undefined,
    workspaceTimeZone: typeof workspace === 'string' ? workspace : workspace === null ? null : undefined,
    effectiveTimeZone: typeof effective === 'string' ? effective : null,
    canManageWorkspaceTimeZone: typeof canManage === 'boolean' ? canManage : undefined,
  }
}

export const timezonePreferences = reactive<TimezonePreferencesState>({
  personalTimeZone: readLocalPersonalTimeZone(),
  workspaceTimeZone: null,
  effectiveTimeZone: DEFAULT_TIMEZONE,
  source: 'utc-fallback',
  warning: null,
  loading: false,
  saving: false,
  canManageWorkspaceTimeZone: false,
  backendAvailable: null,
})

function refreshResolution() {
  const resolution = resolveEffectiveTimeZone(
    timezonePreferences.personalTimeZone,
    timezonePreferences.workspaceTimeZone,
  )
  timezonePreferences.effectiveTimeZone = resolution.timeZone
  timezonePreferences.source = resolution.source
  timezonePreferences.warning = resolution.warning
}

refreshResolution()

export function timezoneSourceLabel(source: TimezonePreferenceSource) {
  return ({ personal: '个人偏好', workspace: '工作区偏好', browser: '浏览器时区', 'utc-fallback': 'UTC 安全回退' } as Record<TimezonePreferenceSource, string>)[source]
}

export async function initializeTimezonePreferences() {
  if (timezonePreferences.loading) return
  const initialRevision = preferenceRevision
  timezonePreferences.loading = true
  timezonePreferences.warning = null
  // Local storage gives an immediate, deterministic value while the optional
  // backend contract is loading.
  timezonePreferences.personalTimeZone = readLocalPersonalTimeZone()
  refreshResolution()
  try {
    const response = await fetch(TIMEZONE_ENDPOINT, { headers: { Accept: 'application/json' } })
    if (response.status === 404 || response.status === 405) {
      timezonePreferences.backendAvailable = false
      timezonePreferences.warning = '偏好接口尚未接入，当前使用本机保存的个人时区。'
      return
    }
    if (!response.ok) throw new Error(`偏好读取失败（${response.status}）`)
    const payload = normaliseResponse(await response.json())
    timezonePreferences.backendAvailable = true
    if (payload.personalTimeZone !== undefined && preferenceRevision === initialRevision) {
      timezonePreferences.personalTimeZone = payload.personalTimeZone
      writeLocalPersonalTimeZone(payload.personalTimeZone)
    }
    if (payload.workspaceTimeZone !== undefined && preferenceRevision === initialRevision) timezonePreferences.workspaceTimeZone = payload.workspaceTimeZone
    if (payload.canManageWorkspaceTimeZone !== undefined) timezonePreferences.canManageWorkspaceTimeZone = payload.canManageWorkspaceTimeZone === true
    refreshResolution()
  } catch {
    timezonePreferences.backendAvailable = false
    refreshResolution()
    timezonePreferences.warning = '偏好接口暂时不可用，已使用本机或浏览器时区。'
  } finally {
    timezonePreferences.loading = false
  }
}

export interface SaveTimezoneResult {
  ok: boolean
  message: string
  kind: 'success' | 'info' | 'error'
}

export async function saveTimezonePreference(scope: TimezoneSaveScope, value: string | null): Promise<SaveTimezoneResult> {
  const nextValue = value?.trim() || null
  if (nextValue && !isSupportedTimeZone(nextValue)) {
    return { ok: false, kind: 'error', message: '请输入受支持的 IANA 时区，例如 Asia/Shanghai。' }
  }
  if (scope === 'workspace' && !timezonePreferences.canManageWorkspaceTimeZone) {
    return { ok: false, kind: 'error', message: '当前账号没有修改工作区时区的权限。' }
  }

  const previousPersonal = timezonePreferences.personalTimeZone
  const previousWorkspace = timezonePreferences.workspaceTimeZone
  ++preferenceRevision
  timezonePreferences.saving = true
  try {
    const response = await fetch(TIMEZONE_ENDPOINT, {
      method: 'PUT',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, timezone: nextValue }),
    })
    if (response.status === 404 || response.status === 405) {
      if (scope === 'personal') {
        timezonePreferences.personalTimeZone = nextValue
        writeLocalPersonalTimeZone(nextValue)
        refreshResolution()
        timezonePreferences.backendAvailable = false
        return { ok: true, kind: 'info', message: '偏好接口尚未接入，个人时区已保存在本机。' }
      }
      return { ok: false, kind: 'error', message: '偏好接口尚未接入，暂时无法保存工作区时区。' }
    }
    if (response.status === 401 || response.status === 403) {
      return { ok: false, kind: 'error', message: '保存失败：当前账号没有修改该时区的权限，已保留旧值。' }
    }
    if (!response.ok) {
      return { ok: false, kind: 'error', message: `保存失败（${response.status}），已保留旧值。` }
    }

    const payload = normaliseResponse(await response.json().catch(() => ({})))
    const returnedValue = scope === 'personal' ? payload.personalTimeZone : payload.workspaceTimeZone
    if (returnedValue && !isSupportedTimeZone(returnedValue)) {
      timezonePreferences.personalTimeZone = previousPersonal
      timezonePreferences.workspaceTimeZone = previousWorkspace
      refreshResolution()
      return { ok: false, kind: 'error', message: '接口返回了无效时区，已保留旧值。' }
    }
    if (scope === 'personal') {
      timezonePreferences.personalTimeZone = payload.personalTimeZone !== undefined ? payload.personalTimeZone : nextValue
      writeLocalPersonalTimeZone(timezonePreferences.personalTimeZone)
    } else {
      timezonePreferences.workspaceTimeZone = payload.workspaceTimeZone !== undefined ? payload.workspaceTimeZone : nextValue
    }
    refreshResolution()
    timezonePreferences.backendAvailable = true
    return { ok: true, kind: 'success', message: '时区偏好已保存，所有时间显示已立即更新。' }
  } catch {
    // An offline personal preference can still be used safely on this device;
    // workspace preferences must remain server-authoritative.
    if (scope === 'personal') {
      timezonePreferences.personalTimeZone = nextValue
      writeLocalPersonalTimeZone(nextValue)
      refreshResolution()
      timezonePreferences.backendAvailable = false
      return { ok: true, kind: 'info', message: '当前离线，个人时区已保存在本机；联网后可同步工作区。' }
    }
    timezonePreferences.personalTimeZone = previousPersonal
    timezonePreferences.workspaceTimeZone = previousWorkspace
    refreshResolution()
    return { ok: false, kind: 'error', message: '当前离线，工作区时区未保存，已保留旧值。' }
  } finally {
    timezonePreferences.saving = false
  }
}

export type DateTimePrecision = 'minute' | 'second' | 'millisecond'

export interface FormatDateTimeOptions {
  precision?: DateTimePrecision
  timeZone?: string
}

function parseTimestamp(value: string | Date | null | undefined): Date | null {
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

export function formatDateTime(value: string | Date | null | undefined, options: FormatDateTimeOptions = {}) {
  const parsed = parseTimestamp(value)
  if (!parsed) return '--'
  const configuredTimeZone = options.timeZone ?? timezonePreferences.effectiveTimeZone
  const timeZone = isSupportedTimeZone(configuredTimeZone) ? configuredTimeZone : DEFAULT_TIMEZONE
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

export function formatDateTimeTitle(value: string | Date | null | undefined) {
  const parsed = parseTimestamp(value)
  return parsed ? `原始 UTC：${parsed.toISOString()}` : '原始 UTC：不可用'
}

export function getCurrentUtcIso() {
  return new Date().toISOString()
}

export function formatDateTimeWithTimeZone(value: string | Date | null | undefined, timeZone: string, options: Omit<FormatDateTimeOptions, 'timeZone'> = {}) {
  return formatDateTime(value, { ...options, timeZone })
}
