// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TimezoneSettingsView from './timezone-settings-view.vue'
import { initializeTimezonePreferences, timezonePreferences } from './timezone'

describe('timezone settings view', () => {
  beforeEach(() => {
    timezonePreferences.personalTimeZone = null
    timezonePreferences.workspaceTimeZone = 'Asia/Shanghai'
    timezonePreferences.effectiveTimeZone = 'Asia/Shanghai'
    timezonePreferences.source = 'workspace'
    timezonePreferences.warning = null
    timezonePreferences.loading = false
    timezonePreferences.saving = false
    timezonePreferences.canManageWorkspaceTimeZone = false
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the effective source and rejects an invalid IANA value', async () => {
    const wrapper = mount(TimezoneSettingsView)
    await wrapper.find('input').setValue('Mars/Olympus')
    await wrapper.find('button.settings-save').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请输入受支持的 IANA 时区')
    expect(timezonePreferences.personalTimeZone).toBe(null)
  })

  it('persists a personal timezone when the preference endpoint succeeds', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ personalTimeZone: 'America/New_York' }) }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(TimezoneSettingsView)
    await wrapper.find('input').setValue('America/New_York')
    await wrapper.find('button.settings-save').trigger('click')
    await flushPromises()
    expect(timezonePreferences.personalTimeZone).toBe('America/New_York')
    expect(wrapper.text()).toContain('时区偏好已保存')
    expect(window.localStorage.getItem('a-stock.personal-time-zone')).toBe('America/New_York')
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ scope: 'personal', timezone: 'America/New_York' })
  })

  it('keeps the old workspace value when the account lacks permission', async () => {
    const wrapper = mount(TimezoneSettingsView)
    const inputs = wrapper.findAll('input')
    await inputs[1].setValue('Europe/London')
    await wrapper.findAll('button.settings-save')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('没有修改工作区时区的权限')
    expect(timezonePreferences.workspaceTimeZone).toBe('Asia/Shanghai')
  })

  it('restores a local personal preference when the optional API is not deployed', async () => {
    window.localStorage.setItem('a-stock.personal-time-zone', 'Asia/Tokyo')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))
    await initializeTimezonePreferences()
    expect(timezonePreferences.personalTimeZone).toBe('Asia/Tokyo')
    expect(timezonePreferences.effectiveTimeZone).toBe('Asia/Tokyo')
    expect(timezonePreferences.warning).toContain('接口尚未接入')
  })
})
