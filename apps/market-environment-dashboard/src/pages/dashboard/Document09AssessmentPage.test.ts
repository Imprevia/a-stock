// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document09AssessmentPage from './Document09AssessmentPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(withAssessment: boolean) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'ok',
      coverage: 0.9,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: withAssessment
        ? {
            state: 'trend',
            score: 72.5,
            confidence: 'high',
            evidence: ['五指数同步上涨', '放量确认'],
            risks: ['外围波动风险'],
            nextConfirmation: '次日上涨占比 ≥ 60%',
            invalidation: '跌破 MA20 且放量',
          }
        : { state: 'insufficient', confidence: 'insufficient', evidence: [], risks: [], nextConfirmation: null, invalidation: null },
    },
  }
}

async function mountPage(withAssessment: boolean) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(withAssessment) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/09')
  await router.isReady()
  const wrapper = mount(Document09AssessmentPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document09AssessmentPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the single conclusion with score, confidence and coverage', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('唯一结论')
    expect(wrapper.text()).toContain('趋势')
    expect(wrapper.text()).toContain('72.5 分')
    expect(wrapper.text()).toContain('置信度 高')
    expect(wrapper.text()).toContain('覆盖率 90%')
    expect(wrapper.text()).toContain('经验阈值仍处于待回测状态')
  })

  it('renders evidence chain, risks and verification panels', async () => {
    const wrapper = await mountPage(true)
    expect(wrapper.text()).toContain('支持当前判断')
    expect(wrapper.text()).toContain('五指数同步上涨')
    expect(wrapper.text()).toContain('不可忽略的风险')
    expect(wrapper.text()).toContain('外围波动风险')
    expect(wrapper.text()).toContain('次日上涨占比 ≥ 60%')
    expect(wrapper.text()).toContain('跌破 MA20 且放量')
  })

  it('renders the insufficient fallbacks when assessment is empty', async () => {
    const wrapper = await mountPage(false)
    expect(wrapper.text()).toContain('数据不足')
    expect(wrapper.text()).toContain('分数不足')
    expect(wrapper.text()).toContain('暂无完整证据链')
    expect(wrapper.text()).toContain('当前未返回已触发的风险否决')
    expect(wrapper.text()).toContain('数据不足，等待新增证据')
  })
})