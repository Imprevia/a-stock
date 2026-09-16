// @vitest-environment happy-dom

import { setActivePinia, createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document08EnvironmentClassifyPage from './Document08EnvironmentClassifyPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'

function makeResponse(state: string | null, evidence: string[]) {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'ok',
      coverage: 0.8,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state, confidence: 'medium', evidence, risks: [], nextConfirmation: '', invalidation: '' },
    },
  }
}

async function mountPage(state: string | null, evidence: string[]) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(state, evidence) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/08')
  await router.isReady()
  const wrapper = mount(Document08EnvironmentClassifyPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('Document08EnvironmentClassifyPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the environment label with confidence and coverage', async () => {
    const wrapper = await mountPage('trend', ['五指数 MA20 上方 4 个', '上涨占比 62%'])
    expect(wrapper.text()).toContain('当前环境')
    expect(wrapper.text()).toContain('趋势')
    expect(wrapper.text()).toContain('置信度 中')
    expect(wrapper.text()).toContain('规则覆盖 80%')
  })

  it('renders the evidence list items', async () => {
    const wrapper = await mountPage('rotation', ['量能比值 1.1x'])
    expect(wrapper.text()).toContain('风险优先分类')
    expect(wrapper.text()).toContain('量能比值 1.1x')
    expect(wrapper.text()).not.toContain('有效证据链不足')
  })

  it('renders the muted row when evidence is empty', async () => {
    const wrapper = await mountPage('insufficient', [])
    expect(wrapper.text()).toContain('数据不足')
    expect(wrapper.text()).toContain('有效证据链不足，暂不归类为趋势、轮动或退潮。')
  })
})