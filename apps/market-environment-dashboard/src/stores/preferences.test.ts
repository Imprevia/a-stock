// @vitest-environment happy-dom

import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  usePreferencesStore,
  isSupportedTimeZone,
  resolveEffectiveTimeZone,
} from './preferences'

describe('preferences store — load', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('populates store from /api/preferences/timezone when backend is available', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        personalTimeZone: 'Asia/Shanghai',
        workspaceTimeZone: 'Asia/Tokyo',
        effectiveTimeZone: 'Asia/Shanghai',
        canManageWorkspaceTimeZone: true,
      }),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    await store.load()

    expect(store.personalTimeZone).toBe('Asia/Shanghai')
    expect(store.workspaceTimeZone).toBe('Asia/Tokyo')
    expect(store.effectiveTimeZone).toBe('Asia/Shanghai')
    expect(store.canManageWorkspaceTimeZone).toBe(true)
    expect(store.backendAvailable).toBe(true)
    expect(store.loading).toBe(false)
  })

  it('falls back to local storage when backend returns 404', async () => {
    window.localStorage.setItem('a-stock.personal-time-zone', 'Asia/Shanghai')
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({}),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    await store.load()

    expect(store.backendAvailable).toBe(false)
    expect(store.personalTimeZone).toBe('Asia/Shanghai')
    expect(store.warning).toBe('偏好接口尚未接入，当前使用本机保存的个人时区。')
  })

  it('records the load error and falls back to browser tz when backend fails', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({}),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    await store.load()

    expect(store.backendAvailable).toBe(false)
    expect(store.warning).toBe('偏好接口暂时不可用，已使用本机或浏览器时区。')
  })
})

describe('preferences store — save', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('rejects unsupported IANA timezones without hitting the API', async () => {
    const fetchMock = vi.fn() as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    const result = await store.save('personal', 'Mars/Olympus')

    expect(result.ok).toBe(false)
    expect(result.kind).toBe('error')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects workspace saves when canManageWorkspaceTimeZone is false', async () => {
    const fetchMock = vi.fn() as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    const result = await store.save('workspace', 'Asia/Tokyo')

    expect(result.ok).toBe(false)
    expect(result.message).toContain('权限')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('PUTs the personal preference and refreshes store on 200', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        personalTimeZone: 'Asia/Tokyo',
        effectiveTimeZone: 'Asia/Tokyo',
      }),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    const result = await store.save('personal', 'Asia/Tokyo')

    expect(result.ok).toBe(true)
    expect(result.kind).toBe('success')
    expect(store.personalTimeZone).toBe('Asia/Tokyo')
    expect(store.effectiveTimeZone).toBe('Asia/Tokyo')
    expect(store.backendAvailable).toBe(true)
    expect(window.localStorage.getItem('a-stock.personal-time-zone')).toBe('Asia/Tokyo')
  })

  it('falls back to local storage on 404 for personal scope', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({}),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = usePreferencesStore()
    const result = await store.save('personal', 'Asia/Tokyo')

    expect(result.ok).toBe(true)
    expect(result.kind).toBe('info')
    expect(store.personalTimeZone).toBe('Asia/Tokyo')
    expect(window.localStorage.getItem('a-stock.personal-time-zone')).toBe('Asia/Tokyo')
  })
})

describe('preferences store — pure helpers', () => {
  it('isSupportedTimeZone accepts valid IANA ids', () => {
    expect(isSupportedTimeZone('Asia/Shanghai')).toBe(true)
    expect(isSupportedTimeZone('UTC')).toBe(true)
  })

  it('isSupportedTimeZone rejects invalid ids', () => {
    expect(isSupportedTimeZone('Mars/Olympus')).toBe(false)
    expect(isSupportedTimeZone(null)).toBe(false)
    expect(isSupportedTimeZone(undefined)).toBe(false)
    expect(isSupportedTimeZone('')).toBe(false)
  })

  it('resolveEffectiveTimeZone prefers personal over workspace over browser', () => {
    expect(resolveEffectiveTimeZone('Asia/Shanghai', 'Asia/Tokyo', 'UTC').source).toBe('personal')
    expect(resolveEffectiveTimeZone(null, 'Asia/Tokyo', 'UTC').source).toBe('workspace')
    expect(resolveEffectiveTimeZone(null, null, 'UTC').source).toBe('browser')
    expect(resolveEffectiveTimeZone(null, null, null).source).toBe('utc-fallback')
  })
})