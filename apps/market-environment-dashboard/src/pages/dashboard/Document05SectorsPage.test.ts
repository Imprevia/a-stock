// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document05SectorsPage from './Document05SectorsPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withRows: boolean) {
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
      sectors: withRows
        ? {
            state: '轮动加速',
            rows: [
              { code: 'ai', name: '人工智能', changePct: 2.35, upCount: 120, downCount: 30, mainNet: 1500000000, leader: '某AI股' },
              { code: 'semi', name: '半导体', changePct: -1.2, upCount: 40, downCount: 110, mainNet: -300000000, leader: null },
            ],
            quality: { dataset: 'industry-ranking', source: 'fixture', provider: 'fixture', status: 'ok', observations: 86, asOf: '2026-09-03', warnings: [] },
          }
        : {
            state: 'insufficient',
            rows: [],
            quality: { dataset: 'industry-ranking', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-03', warning: '行业排名未返回', warnings: [] },
          },
    },
  }
}

async function mountPage(withRows: boolean) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withRows) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/05')
  await router.isReady()
  const wrapper = mount(Document05SectorsPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document05SectorsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the sector table rows with tone classes', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('轮动加速')
    expect(wrapper.text()).toContain('人工智能')
    expect(wrapper.text()).toContain('半导体')
    expect(wrapper.text()).toContain('+2.35%')
    expect(wrapper.text()).toContain('-1.20%')
    expect(wrapper.text()).toContain('某AI股')
    expect(wrapper.text()).toContain('15.0 亿')
    expect(wrapper.text()).toContain('-3.0 亿')
  })

  it('renders the empty fallback when sectors has no rows', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('板块数据不足')
    expect(wrapper.text()).toContain('行业排名未返回')
  })

  it('renders the default fallback text when warning is absent', async () => {
    setActivePinia(createPinia())
    const market = useMarketStore()
    const response = makeResponse(false) as { chapter01: { sectors: { quality: Record<string, unknown> } } }
    delete response.chapter01.sectors.quality.warning
    market.data = response as never
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/dashboard/05')
    await router.isReady()
    const wrapper = mount(Document05SectorsPage, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('行业相对强度、成交持续性、板块宽度和集中度尚未返回。')
  })
})