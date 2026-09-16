// @vitest-environment happy-dom


vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))
import { setActivePinia, createPinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document01IndexPricePage from './Document01IndexPricePage.vue'
import { useMarketStore } from '../../stores/market'

function historyPoint(date: string, overrides: Partial<Record<string, unknown>> = {}) {
  return {
    date,
    open: 100,
    close: 101,
    low: 99,
    high: 102,
    ma5: 100.5,
    ma10: 100.2,
    ma20: 100,
    ma60: 99,
    amount: 50000000,
    ...overrides,
  }
}

function indexItem(position: number) {
  const names = ['上证指数', '深证成指', '创业板指', '沪深300', '中证500']
  return {
    code: `index-${position}`,
    name: names[position],
    representative: 'fixture',
    changePct: (position + 1) / 10,
    close: 100 + position,
    movingAverages: { ma5: 102, ma10: 101, ma20: 100, ma60: 99 },
    rangePosition20: 0.6,
    rangePosition60: 0.5,
    rangePosition20Label: '偏强区域',
    rangePosition60Label: '区间中部',
    amount: 1000000000,
    amountRatio5: 1.1,
    amountRatio20: 1,
    trendState: '偏强',
    volumePriceState: '量价平稳',
    combination: {
      key: 'rotation',
      state: '震荡轮动',
      matched: true,
      tone: 'neutral',
      evidence: [`${names[position]} evidence`],
      tradingMode: '轮动应对',
    },
    history: [
      historyPoint('2026-08-01'),
      historyPoint('2026-08-02'),
      historyPoint('2026-08-03'),
    ],
    dataQuality: { source: 'fixture', isStale: false, warning: null },
    dataGaps: [],
  }
}

function makeResponse(asOf = '2026-09-03') {
  return {
    asOf,
    generatedAt: `${asOf}T16:00:00+08:00`,
    indices: Array.from({ length: 5 }, (_, index) => indexItem(index)),
    summary: {
      synchronization: 'fixture',
      syncPattern: { code: 'synchronized_rally', label: '多数指数同步上涨', score: 4, evidence: ['上证指数 +1.00%', '沪深300 +0.90%'] },
      synchronizationAssessment: {
        patternCode: 'synchronized_rally',
        patternLabel: '多数指数同步上涨',
        status: 'confirmed',
        conclusionCode: 'fixture',
        conclusion: '多数指数同步上涨且市场广度确认。',
        confidence: 'high',
        allFiveWeak: false,
        dimensions: {
          breadth: {
            status: 'confirming',
            currentAsOf: '2026-09-03',
            previousAsOf: '2026-09-02',
            advanceRatio: 0.62,
            medianReturn: 0.7,
            advanceRatioDelta: 0.07,
            medianReturnDelta: 0.2,
            comparisonStatus: 'available',
            reason: null,
            comparisonReason: null,
            evidence: ['上涨占比 62%', '较 2026-09-02 市场广度改善'],
          },
          trend: {
            status: 'confirming',
            aboveMa20Count: 4,
            belowMa20Count: 1,
            validCount: 5,
            reason: null,
            evidence: ['MA20 上方 4 个，下方 1 个，有效 5 个'],
          },
          turnover: {
            status: 'confirming',
            medianAmountRatio5: 1.12,
            growthMedianAmountRatio5: 1.1,
            volumeBackedAdvanceCount: 3,
            volumeBackedDeclineCount: 0,
            validCount: 5,
            reason: null,
            evidence: ['5 日成交额比值有效 5 个，放量上涨 3 个，放量下跌 0 个'],
          },
        },
        evidence: ['上证指数 +1.00%', '沪深300 +0.90%'],
        risks: ['指数与个股表现背离'],
      } as never,
      dominantTrend: '偏强',
      warnings: [],
    },
    chapter01: {
      status: 'ok',
      coverage: 0.8,
      combinationOverview: {
        strength: '指数分化', stage: '组合分化', capitalAcceptance: '量价分化', tradingMode: '保持观察', confidence: 'low', evidence: [],
      },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      reviewSentence: {
        status: 'available',
        template: 'fixture',
        segments: [],
        fullSentence: '多数指数同步上涨且市场广度确认。',
        warnings: [],
      } as never,
    },
  }
}

function mountPage(response: ReturnType<typeof makeResponse> | null) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = response as never
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/dashboard/01', component: { template: '<div/>' } }] })
  const wrapper = mount(Document01IndexPricePage, {
    global: { plugins: [router] },
  })
  return wrapper
}

describe('Document01IndexPricePage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('renders the index cards section for all 5 indices', async () => {
    const wrapper = mountPage(makeResponse())
    await flushPromises()
    const cards = wrapper.findAll('.index-card')
    expect(cards).toHaveLength(5)
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('index-0')
  })

  it('renders the workspace grid with chart panel and structure panel', async () => {
    const wrapper = mountPage(makeResponse())
    await flushPromises()
    expect(wrapper.find('.workspace-grid').exists()).toBe(true)
    expect(wrapper.find('.chart-panel').exists()).toBe(true)
    expect(wrapper.find('.detail-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('60 日走势')
    expect(wrapper.text()).toContain('趋势与量能')
  })

  it('renders the synchronization assessment band', async () => {
    const wrapper = mountPage(makeResponse())
    await flushPromises()
    expect(wrapper.find('.synchronization-assessment-band').exists()).toBe(true)
    expect(wrapper.text()).toContain('多数指数同步上涨')
    expect(wrapper.text()).toContain('市场广度')
    expect(wrapper.text()).toContain('MA20 结构')
    expect(wrapper.text()).toContain('量能确认')
    expect(wrapper.text()).toContain('风险提示')
    expect(wrapper.text()).toContain('指数与个股表现背离')
  })

  it('renders the combination overview panel and the five-index metric table', async () => {
    const wrapper = mountPage(makeResponse())
    await flushPromises()
    expect(wrapper.find('.combination-overview-panel').exists()).toBe(true)
    expect(wrapper.find('.table-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('四问结论与五指数矩阵')
    expect(wrapper.text()).toContain('五大指数指标表')
    expect(wrapper.text()).toContain('横向比较')
  })

  it('renders without error when market.data is null', async () => {
    const wrapper = mountPage(null)
    await flushPromises()
    // No error panel because market.error is undefined (no fetch failure)
    expect(wrapper.findAll('.index-card')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('行情暂时不可不可用')
  })

  it('emits selectIndex when a card is clicked', async () => {
    const wrapper = mountPage(makeResponse())
    await flushPromises()
    const firstCard = wrapper.findAll('.index-card')[0]
    await firstCard.trigger('click')
    const events = wrapper.emitted('selectIndex')
    expect(events).toBeTruthy()
    expect(events![0]).toEqual(['index-0'])
  })
})