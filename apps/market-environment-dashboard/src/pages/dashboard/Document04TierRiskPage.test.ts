// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document04TierRiskPage from './Document04TierRiskPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withTierRisk: boolean) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'degraded',
      coverage: 0.4,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      tierRisk: withTierRisk
        ? {
            state: '高位扩散',
            high: 6,
            middle: 12,
            low: 4,
            repairRatio: 0.35,
            quality: { dataset: 'tier-risk', source: 'fixture', status: 'ok', observations: 22, asOf: '2026-09-03', warning: '分层样本待回测', warnings: ['分层样本待回测'] },
          }
        : undefined,
    },
  }
}

async function mountPage(withTierRisk: boolean) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withTierRisk) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/04')
  await router.isReady()
  const wrapper = mount(Document04TierRiskPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document04TierRiskPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the four metric cards with tier risk values', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('高位风险')
    expect(wrapper.text()).toContain('中位风险')
    expect(wrapper.text()).toContain('低位风险')
    expect(wrapper.text()).toContain('修复率')
    expect(wrapper.text()).toContain('高位扩散')
    expect(wrapper.text()).toContain('35%')
  })

  it('renders the fallback warning text when tierRisk is missing', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('数据不足')
    expect(wrapper.text()).toContain('分层样本必须独立计算')
    expect(wrapper.text()).toContain('不按安全状态处理')
  })

  it('renders the quality warning from tierRisk when present', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('分层样本待回测')
  })
})