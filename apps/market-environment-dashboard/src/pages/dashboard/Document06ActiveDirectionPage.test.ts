// @vitest-environment happy-dom

import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document06ActiveDirectionPage from './Document06ActiveDirectionPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withStocks: boolean) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'degraded',
      coverage: 0.5,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      activeDirection: withStocks
        ? {
            state: '容量集中',
            summary: '成交额前 30 聚集于算力方向。',
            topStocks: [
              { code: '600000', name: '某算力股', changePct: 5.2, amount: 3200000000, industry: '算力', closePosition: 0.92 },
              { code: '300001', name: '某半导体股', changePct: -2.1, amount: 1800000000, industry: null, closePosition: null },
            ],
            quality: { dataset: 'active-direction', source: 'fixture', provider: 'fixture', status: 'ok', observations: 30, asOf: '2026-09-03', warnings: [] },
          }
        : {
            state: 'insufficient',
            summary: null,
            topStocks: [],
            quality: { dataset: 'active-direction', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-03', warning: '成交额排名未返回', warnings: [] },
          },
    },
  }
}

async function mountPage(withStocks: boolean) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withStocks) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/06')
  await router.isReady()
  const wrapper = mount(Document06ActiveDirectionPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document06ActiveDirectionPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the top stocks table with amounts and positions', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('容量集中')
    expect(wrapper.text()).toContain('成交额前 30 聚集于算力方向。')
    expect(wrapper.text()).toContain('某算力股')
    expect(wrapper.text()).toContain('+5.20%')
    expect(wrapper.text()).toContain('-2.10%')
    expect(wrapper.text()).toContain('32.0 亿')
    expect(wrapper.text()).toContain('92%')
    expect(wrapper.text()).toContain('--')
  })

  it('renders the empty fallback when topStocks is empty', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('未确认容量进攻方向')
    expect(wrapper.text()).toContain('成交额排名未返回')
  })
})