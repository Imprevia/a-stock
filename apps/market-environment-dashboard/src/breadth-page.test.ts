// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from './App.vue'
import { routes } from './router/routes'

const mockEchartsSetOption = vi.hoisted(() => vi.fn())
const mockEchartsDispose = vi.hoisted(() => vi.fn())
const mockEchartsInit = vi.hoisted(() => vi.fn(() => ({
  setOption: mockEchartsSetOption,
  resize: vi.fn(),
  dispose: mockEchartsDispose,
})))

vi.mock('echarts', () => ({ init: mockEchartsInit }))

let wrapper: VueWrapper | null = null

interface BreadthFixture {
  widthLabel: string
  widthLabelReason: string
  history: Array<{
    asOf: string
    advanceCount: number
    declineCount: number
    flatCount: number
    validCount: number
    advanceRatio: number
    declineRatio: number
    advanceDeclineSpread: number
    medianReturn: number
    momentum: number | null
    widthLabel: string
    indexConsistent: boolean | null
    quality: { dataset: string; source: string; provider: string; status: string; observations: number; asOf: string; warnings: string[] }
  }>
}

function buildHistoryFixture(): BreadthFixture['history'] {
  return [
    {
      asOf: '2026-09-12',
      advanceCount: 2103,
      declineCount: 2412,
      flatCount: 87,
      validCount: 4602,
      advanceRatio: 0.4568,
      declineRatio: 0.5241,
      advanceDeclineSpread: -0.0671,
      medianReturn: -0.0042,
      momentum: null,
      widthLabel: '同向走弱',
      indexConsistent: true,
      quality: { dataset: 'market-breadth', source: 'eastmoney-clist', provider: 'eastmoney-clist', status: 'ok', observations: 4602, asOf: '2026-09-12', warnings: [] },
    },
    {
      asOf: '2026-09-15',
      advanceCount: 3156,
      declineCount: 1488,
      flatCount: 87,
      validCount: 4731,
      advanceRatio: 0.6671,
      declineRatio: 0.3145,
      advanceDeclineSpread: 0.3526,
      medianReturn: 0.0071,
      momentum: 0.082,
      widthLabel: '同向增强',
      indexConsistent: true,
      quality: { dataset: 'market-breadth', source: 'eastmoney-clist', provider: 'eastmoney-clist', status: 'ok', observations: 4731, asOf: '2026-09-15', warnings: [] },
    },
  ]
}

function indexFixture(changePct: number, position: number) {
  const names = ['上证指数', '深证成指', '创业板指', '沪深300', '中证500']
  return {
    code: `index-${position}`,
    name: names[position],
    representative: 'fixture',
    changePct,
    close: 100 + position,
    movingAverages: { ma5: 102, ma10: 101, ma20: 100, ma60: 99 },
    rangePosition20: 0.5,
    rangePosition60: 0.5,
    rangePosition20Label: 'fixture',
    rangePosition60Label: 'fixture',
    amount: 1_000_000_000,
    amountRatio5: 1.0,
    amountRatio20: 1.0,
    trendState: 'fixture',
    volumePriceState: 'fixture',
    combination: { key: 'unclassified', state: null, matched: false, tone: 'flat', evidence: [], tradingMode: 'fixture' },
    history: [],
    dataQuality: { source: 'fixture', isStale: false, warning: null },
    dataGaps: [],
  }
}

function makeResponse() {
  return {
    asOf: '2026-09-16',
    generatedAt: '2026-09-16T16:00:00+08:00',
    indices: [
      indexFixture(0.62, 0),
      indexFixture(0.38, 1),
      indexFixture(-0.15, 2),
      indexFixture(0.71, 3),
      indexFixture(0.09, 4),
    ],
    summary: {
      synchronization: 'fixture',
      dominantTrend: 'fixture',
      warnings: [],
    },
    chapter01: {
      status: 'partial',
      coverage: 0.5,
      documents: [],
      breadth: {
        advanceCount: 3212,
        declineCount: 1489,
        flatCount: 87,
        validCount: 4788,
        advanceRatio: 0.6708,
        medianReturn: 0.0084,
        state: '多数上涨',
        quality: {
          dataset: 'market-breadth',
          source: 'eastmoney-clist',
          provider: 'eastmoney-clist',
          status: 'partial',
          observations: 4788,
          asOf: '2026-09-16',
          warnings: [],
        },
        declineRatio: 0.3110,
        advanceDeclineSpread: 0.3598,
        advanceRatioPercentile: 0.78,
        medianReturnPercentile: 0.55,
        spreadPercentile: 0.65,
        momentum: 0.082,
        momentumPercentile: 0.70,
        indexConsistent: true,
        widthLabel: '同向增强',
        widthLabelReason: '上涨占比 67% 与中位数 +0.84% 同向且较前一日共同改善。',
        history: {
          points: buildHistoryFixture(),
          validObservations: 60,
          requiredObservations: 60,
          windowDays: 250,
          coverage: 0.24,
          percentile250: {
            advanceRatio: 0.78,
            medianReturn: 0.55,
            advanceDeclineSpread: 0.65,
            momentum: 0.70,
          },
          quality: { status: 'ok', reason: null, observations: 60, asOf: '2026-09-16', source: 'eastmoney-clist', warnings: [] },
        },
      },
      limits: {
        limitUpCount: null,
        limitDownCount: null,
        failedLimitUpCount: null,
        failedLimitUpRatio: null,
        maxStreak: null,
        state: 'insufficient',
        quality: { dataset: 'limit-pools', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-16', warnings: [] },
      },
      sectors: { rows: [], state: 'insufficient', quality: { dataset: 'industry-ranking', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-16', warnings: [] } },
      activeDirection: { state: 'insufficient', summary: null, topStocks: [], quality: { dataset: 'active-direction', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-16', warnings: [] } },
      events: { state: 'unverified', items: [], quality: { dataset: 'traceable-events', source: 'fixture', provider: 'fixture', status: 'missing', observations: 0, asOf: '2026-09-16', warnings: [] } },
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
    },
  }
}

async function mountDocument02() {
  // Route to the breadth document via vue-router; the App reads the path on mount.
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => makeResponse(),
  }))
  vi.stubGlobal('fetch', fetchMock)
  setActivePinia(createPinia())
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/02')
  await router.isReady()
  wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  await flushPromises()
  await flushPromises()
}

beforeEach(() => {
  mockEchartsInit.mockClear()
  mockEchartsSetOption.mockClear()
  mockEchartsDispose.mockClear()
})

afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
  vi.unstubAllGlobals()
})

describe('breadth page rendering', () => {
  it('renders the recap, rules, history, consistency and verification sections', async () => {
    await mountDocument02()
    const html = wrapper!.html()
    expect(html).toContain('盘后复盘卡')
    expect(html).toContain('量化证据 · QTS-01-02-01..05')
    expect(html).toContain('近 5 日宽度趋势')
    expect(html).toContain('五个指数与广度一致性')
    expect(html).toContain('次交易日验证')
  })

  it('shows the active width label pill and reason text', async () => {
    await mountDocument02()
    const html = wrapper!.html()
    expect(html).toContain('同向增强')
    expect(html).toContain('上涨占比 67% 与中位数 +0.84% 同向且较前一日共同改善')
  })

  it('exposes five rule rows with percentile bars and weight labels', async () => {
    await mountDocument02()
    const html = wrapper!.html()
    expect(html).toContain('QTS-01-02-01')
    expect(html).toContain('QTS-01-02-02')
    expect(html).toContain('QTS-01-02-03')
    expect(html).toContain('QTS-01-02-04')
    expect(html).toContain('QTS-01-02-05')
    expect(html).toContain('30%')
    expect(html).toContain('20%')
    expect(html).toContain('10%')
  })

  it('renders the five-day history table rows', async () => {
    await mountDocument02()
    const html = wrapper!.html()
    expect(html).toContain('2026-09-12')
    expect(html).toContain('2026-09-15')
    expect(html).toContain('同向走弱')
    expect(html).toContain('同向增强')
  })

  it('renders the index × breadth consistency matrix with five rows', async () => {
    await mountDocument02()
    const html = wrapper!.html()
    const rows = wrapper!.findAll('.breadth-consistency-table tbody tr')
    expect(rows.length).toBe(5)
    // 4 of 5 indices align with the positive median => majority consistent.
    expect(html).toContain('多数一致')
  })

  it('exposes a copy verification button', async () => {
    await mountDocument02()
    expect(wrapper!.html()).toContain('复制验证项')
  })

  it('does not introduce horizontal overflow at 390px viewport', async () => {
    await mountDocument02()
    // Force a mobile viewport and re-render by reading computed styles.
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 844 })
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    const main = wrapper!.find('.content-shell').element as HTMLElement
    // The app shell enforces width clamp; the content shell should never exceed the viewport.
    expect(main.scrollWidth).toBeLessThanOrEqual(390)
  })
})