// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from '../../App.vue'
import { registerRouterGuards } from '../../router/guards'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))

let wrapper: VueWrapper | null = null

const baseChapter = {
  status: 'degraded',
  coverage: 0.2,
  combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'insufficient', evidence: [] },
  assessment: { state: 'insufficient', confidence: 'insufficient', evidence: [], risks: [], nextConfirmation: null, invalidation: null },
}

function limitsEvidence(asOf: string) {
  return {
    limitUpCount: 10,
    limitDownCount: 2,
    failedLimitUpCount: 3,
    failedLimitUpRatio: 0.2,
    maxStreak: 4,
    state: 'fixture',
    quality: { dataset: 'limits', source: 'fixture', provider: 'fixture', status: 'ok', observations: 10, asOf, warnings: [] },
    stratifications: [],
    riskEvidence: [],
  }
}

function coreResponse(asOf: string) {
  return {
    asOf,
    generatedAt: `${asOf}T16:00:00+08:00`,
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: baseChapter,
  }
}

function sectionResponse(asOf: string) {
  return {
    asOf,
    generatedAt: `${asOf}T16:01:00+08:00`,
    chapter01: { ...baseChapter, limits: limitsEvidence(asOf) },
  }
}

async function mountDashboard(path: '/dashboard/03' | '/dashboard/04') {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: string | URL | Request) => {
    const url = String(request)
    requests.push(url)
    if (url === '/api/preferences/timezone') {
      return { ok: false, status: 404, json: async () => ({}) }
    }
    const parsed = new URL(url, 'http://fixture.local')
    const asOf = parsed.searchParams.get('as_of') ?? '2026-09-10'
    if (parsed.pathname.endsWith('/chapter-01')) {
      return { ok: true, status: 200, json: async () => sectionResponse(asOf) }
    }
    if (parsed.pathname.endsWith('/next-session')) {
      return { ok: true, status: 200, json: async () => ({ status: 'pending', requestedAsOf: asOf, deltas: {}, warnings: [] }) }
    }
    return { ok: true, status: 200, json: async () => coreResponse(asOf) }
  }))

  const pinia = createPinia()
  setActivePinia(pinia)
  const market = useMarketStore()
  market.selectedDate = '2026-09-10'
  const router = createRouter({ history: createMemoryHistory(), routes })
  registerRouterGuards(router)
  await router.push(path)
  await router.isReady()
  wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  await flushPromises()
  return { view: wrapper, requests }
}

describe('DashboardLayout section refresh', () => {
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    vi.unstubAllGlobals()
  })

  it.each(['/dashboard/03', '/dashboard/04'] as const)('切换日期后为 %s 重载 limits', async (path) => {
    const { view, requests } = await mountDashboard(path)
    requests.length = 0

    const input = view.get('input[type="date"]')
    await input.setValue('2026-09-09')
    await input.trigger('change')
    await flushPromises()
    await flushPromises()

    expect(requests).toContain('/api/market-environment/core?as_of=2026-09-09')
    expect(requests).toContain('/api/market-environment/chapter-01?as_of=2026-09-09&section=limits')
  })

  it.each(['/dashboard/03', '/dashboard/04'] as const)('全局刷新后为 %s 重载 limits', async (path) => {
    const { view, requests } = await mountDashboard(path)
    requests.length = 0

    await view.get('button[aria-label="刷新行情"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(requests).toContain('/api/market-environment/core?as_of=2026-09-10')
    expect(requests).toContain('/api/market-environment/chapter-01?as_of=2026-09-10&section=limits')
  })
})
