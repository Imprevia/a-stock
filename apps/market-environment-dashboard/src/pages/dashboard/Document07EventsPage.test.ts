// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document07EventsPage from './Document07EventsPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withItems: boolean) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'unverified',
      coverage: 0.3,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      events: withItems
        ? {
            state: '部分核实',
            items: [
              { title: '某政策发布', source: '官网', publishedAt: '2026-09-03T10:00:00+08:00', verified: true },
              { title: '某外围传闻', source: null, publishedAt: null, verified: false },
            ],
            quality: { dataset: 'traceable-events', source: 'fixture', provider: 'fixture', status: 'partial', observations: 2, asOf: '2026-09-03', warnings: [] },
          }
        : {
            state: 'unverified',
            items: [],
            quality: { dataset: 'traceable-events', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-03', warning: '事件源未接入', warnings: [] },
          },
    },
  }
}

async function mountPage(withItems: boolean) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withItems) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/07')
  await router.isReady()
  const wrapper = mount(Document07EventsPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document07EventsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the event list with source, time and verification badges', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('部分核实')
    expect(wrapper.text()).toContain('某政策发布')
    expect(wrapper.text()).toContain('官网')
    expect(wrapper.text()).toContain('已核实')
    expect(wrapper.text()).toContain('某外围传闻')
    expect(wrapper.text()).toContain('来源未标注')
    expect(wrapper.text()).toContain('时间未标注')
    expect(wrapper.text()).toContain('待核实')
    expect(wrapper.text()).toContain('盘面确认后最多 ±5 分')
  })

  it('renders the empty fallback when no event items exist', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('没有可追溯事件输入')
    expect(wrapper.text()).toContain('事件源未接入')
  })
})