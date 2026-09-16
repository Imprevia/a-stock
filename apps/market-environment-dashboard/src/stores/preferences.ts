/**
 * Preferences store — wraps the user's timezone preferences and the
 * `/api/preferences/timezone` endpoint. Replaces the module-scope
 * `reactive` object in `timezone.ts` with a Pinia setup store while
 * preserving the same fields and the localStorage read/write contract.
 *
 * Pure helpers (`isSupportedTimeZone`, `getBrowserTimeZone`,
 * `resolveEffectiveTimeZone`) stay in `timezone.ts` / future
 * `composables/useFormatDateTime.ts`; the store does NOT expose them.
 * UI components pass `effectiveTimeZone` into the pure `formatDateTime`
 * helper explicitly.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type TimezonePreferenceSource = 'personal' | 'workspace' | 'browser' | 'utc-fallback'
export type TimezoneSaveScope = 'personal' | 'workspace'

export const MARKET_TIME_ZONE = 'Asia/Shanghai'
const TIMEZONE_ENDPOINT = '/api/preferences/timezone'
const LOCAL_STORAGE_KEY = 'a-stock.personal-time-zone'
const DEFAULT_TIMEZONE = 'UTC'

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

export interface TimezoneResolution {
  timeZone: string
  source: TimezonePreferenceSource
  warning: string | null
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

export interface TimezonePreferencesResponse {
  personalTimeZone?: string | null
  workspaceTimeZone?: string | null
  effectiveTimeZone?: string | null
  canManageWorkspaceTimeZone?: boolean
}

export interface SaveTimezoneResult {
  ok: boolean
  message: string
  kind: 'success' | 'info' | 'error'
}

function readLocalPersonalTimeZone(): string | null {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(LOCAL_STORAGE_KEY)
    return value || null
  } catch {
    return null
  }
}

function writeLocalPersonalTimeZone(value: string | null): void {
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
  const personal = value.personalTimeZone ?? value.personalTimezone ?? value.personal_timezone
    ?? personalObject?.timeZone ?? personalObject?.timezone
    ?? value.personal ?? value.timeZone ?? value.timezone
  const workspace = value.workspaceTimeZone ?? value.workspaceTimezone ?? value.workspace_timezone
    ?? workspaceObject?.timeZone ?? workspaceObject?.timezone
    ?? value.workspace
  const effective = value.effectiveTimeZone ?? value.effectiveTimezone ?? value.effective_timezone
    ?? value.effective ?? value.timeZone ?? value.timezone
  const canManage = value.canManageWorkspaceTimeZone ?? value.can_manage_workspace_timezone
  return {
    personalTimeZone: typeof personal === 'string' ? personal : personal === null ? null : undefined,
    workspaceTimeZone: typeof workspace === 'string' ? workspace : workspace === null ? null : undefined,
    effectiveTimeZone: typeof effective === 'string' ? effective : null,
    canManageWorkspaceTimeZone: typeof canManage === 'boolean' ? canManage : undefined,
  }
}

export const usePreferencesStore = defineStore('preferences', () => {
  const personalTimeZone = ref<string | null>(readLocalPersonalTimeZone())
  const workspaceTimeZone = ref<string | null>(null)
  const effectiveTimeZone = ref(DEFAULT_TIMEZONE)
  const source = ref<TimezonePreferenceSource>('utc-fallback')
  const warning = ref<string | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const canManageWorkspaceTimeZone = ref(false)
  const backendAvailable = ref<boolean | null>(null)

  let preferenceRevision = 0

  function refreshResolution(): void {
    const resolution = resolveEffectiveTimeZone(personalTimeZone.value, workspaceTimeZone.value)
    effectiveTimeZone.value = resolution.timeZone
    source.value = resolution.source
    warning.value = resolution.warning
  }

  refreshResolution()

  async function load(): Promise<void> {
    if (loading.value) return
    const initialRevision = preferenceRevision
    loading.value = true
    warning.value = null
    personalTimeZone.value = readLocalPersonalTimeZone()
    refreshResolution()
    try {
      const response = await fetch(TIMEZONE_ENDPOINT, { headers: { Accept: 'application/json' } })
      if (response.status === 404 || response.status === 405) {
        backendAvailable.value = false
        warning.value = '偏好接口尚未接入，当前使用本机保存的个人时区。'
        return
      }
      if (!response.ok) throw new Error(`偏好读取失败（${response.status}）`)
      const payload = normaliseResponse(await response.json())
      backendAvailable.value = true
      if (payload.personalTimeZone !== undefined && preferenceRevision === initialRevision) {
        personalTimeZone.value = payload.personalTimeZone
        writeLocalPersonalTimeZone(payload.personalTimeZone)
      }
      if (payload.workspaceTimeZone !== undefined && preferenceRevision === initialRevision) {
        workspaceTimeZone.value = payload.workspaceTimeZone
      }
      if (payload.canManageWorkspaceTimeZone !== undefined) {
        canManageWorkspaceTimeZone.value = payload.canManageWorkspaceTimeZone === true
      }
      refreshResolution()
    } catch {
      backendAvailable.value = false
      refreshResolution()
      warning.value = '偏好接口暂时不可用，已使用本机或浏览器时区。'
    } finally {
      loading.value = false
    }
  }

  async function save(scope: TimezoneSaveScope, value: string | null): Promise<SaveTimezoneResult> {
    const nextValue = value?.trim() || null
    if (nextValue && !isSupportedTimeZone(nextValue)) {
      return { ok: false, kind: 'error', message: '请输入受支持的 IANA 时区，例如 Asia/Shanghai。' }
    }
    if (scope === 'workspace' && !canManageWorkspaceTimeZone.value) {
      return { ok: false, kind: 'error', message: '当前账号没有修改工作区时区的权限。' }
    }

    const previousPersonal = personalTimeZone.value
    const previousWorkspace = workspaceTimeZone.value
    ++preferenceRevision
    saving.value = true
    try {
      const response = await fetch(TIMEZONE_ENDPOINT, {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, timezone: nextValue }),
      })
      if (response.status === 404 || response.status === 405) {
        if (scope === 'personal') {
          personalTimeZone.value = nextValue
          writeLocalPersonalTimeZone(nextValue)
          refreshResolution()
          backendAvailable.value = false
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
        personalTimeZone.value = previousPersonal
        workspaceTimeZone.value = previousWorkspace
        refreshResolution()
        return { ok: false, kind: 'error', message: '接口返回了无效时区，已保留旧值。' }
      }
      if (scope === 'personal') {
        personalTimeZone.value = payload.personalTimeZone !== undefined ? payload.personalTimeZone : nextValue
        writeLocalPersonalTimeZone(personalTimeZone.value)
      } else {
        workspaceTimeZone.value = payload.workspaceTimeZone !== undefined ? payload.workspaceTimeZone : nextValue
      }
      refreshResolution()
      backendAvailable.value = true
      return { ok: true, kind: 'success', message: '时区偏好已保存，所有时间显示已立即更新。' }
    } catch {
      // An offline personal preference can still be used safely on this device;
      // workspace preferences must remain server-authoritative.
      if (scope === 'personal') {
        personalTimeZone.value = nextValue
        writeLocalPersonalTimeZone(nextValue)
        refreshResolution()
        backendAvailable.value = false
        return { ok: true, kind: 'info', message: '当前离线，个人时区已保存在本机；联网后可同步工作区。' }
      }
      personalTimeZone.value = previousPersonal
      workspaceTimeZone.value = previousWorkspace
      refreshResolution()
      return { ok: false, kind: 'error', message: '当前离线，工作区时区未保存，已保留旧值。' }
    } finally {
      saving.value = false
    }
  }

  return {
    personalTimeZone,
    workspaceTimeZone,
    effectiveTimeZone,
    source,
    warning,
    loading,
    saving,
    canManageWorkspaceTimeZone,
    backendAvailable,
    load,
    save,
  }
})