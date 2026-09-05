// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.vue'
import type { SynchronizationAssessment, SynchronizationDimensionStatus } from './types'

const mockEchartsSetOption = vi.hoisted(() => vi.fn())
const mockEchartsDispose = vi.hoisted(() => vi.fn())
const mockEchartsInit = vi.hoisted(() => vi.fn(() => ({
  setOption: mockEchartsSetOption,
  resize: vi.fn(),
  dispose: mockEchartsDispose,
})))

vi.mock('echarts', () => ({ init: mockEchartsInit }))

const combinations = ['bottom_repair', 'uptrend', 'breakout', 'high_divergence', 'rotation', 'trend_damage']
let mountedWrapper: VueWrapper | null = null

interface AssessmentFixtureOptions {
  patternCode?: string
  patternLabel?: string
  status?: SynchronizationAssessment['status']
  conclusion?: string
  confidence?: SynchronizationAssessment['confidence']
  breadthStatus?: SynchronizationDimensionStatus
  trendStatus?: SynchronizationDimensionStatus
  turnoverStatus?: SynchronizationDimensionStatus
  comparisonAvailable?: boolean
  breadthReason?: string | null
  growthMedianAmountRatio5?: number | null
  aboveMa20Count?: number
  belowMa20Count?: number
  volumeBackedAdvanceCount?: number
  volumeBackedDeclineCount?: number
  risks?: string[]
}

function indexItem(position: number) {
  const names = ['上证指数', '深证成指', '创业板指', '沪深300', '中证500']
  const key = position === 3 ? 'rotation' : 'unclassified'
  return {
    code: `index-${position}`,
    name: names[position],
    representative: 'fixture',
    changePct: position / 10,
    close: 100 + position,
    movingAverages: { ma5: 102, ma10: 101, ma20: 100, ma60: 99 },
    rangePosition20: 0.6,
    rangePosition60: 0.5,
    rangePosition20Label: '偏强区域',
    rangePosition60Label: '区间中部',
    amount: 1000,
    amountRatio5: 1.1,
    amountRatio20: 1,
    trendState: '偏强',
    volumePriceState: '量价平稳',
    combination: {
      key,
      state: key === 'rotation' ? '震荡轮动' : null,
      matched: key !== 'unclassified',
      tone: 'neutral',
      evidence: [`${names[position]} evidence`],
      tradingMode: key === 'rotation' ? '轮动应对' : '保持观察',
    },
    history: [],
    dataQuality: { source: 'fixture', isStale: false, warning: null },
    dataGaps: [],
  }
}

function synchronizationAssessment(options: AssessmentFixtureOptions = {}): SynchronizationAssessment {
  const comparisonAvailable = options.comparisonAvailable ?? true
  return {
    patternCode: options.patternCode ?? 'synchronized_rally',
    patternLabel: options.patternLabel ?? '多数指数同步上涨',
    status: options.status ?? 'confirmed',
    conclusionCode: 'fixture-conclusion',
    conclusion: options.conclusion ?? '章节新结论：多数指数同步上涨且市场广度确认。',
    confidence: options.confidence ?? 'high',
    allFiveWeak: false,
    dimensions: {
      breadth: {
        status: options.breadthStatus ?? 'confirming',
        currentAsOf: '2026-09-03',
        previousAsOf: comparisonAvailable ? '2026-09-02' : null,
        advanceRatio: 0.62,
        medianReturn: 0.7,
        advanceRatioDelta: comparisonAvailable ? 0.07 : null,
        medianReturnDelta: comparisonAvailable ? 0.2 : null,
        comparisonStatus: comparisonAvailable ? 'available' : 'insufficient',
        reason: options.breadthReason ?? null,
        comparisonReason: comparisonAvailable ? null : 'previous-breadth-unavailable',
        evidence: comparisonAvailable
          ? ['上涨占比 62%，涨跌幅中位数 0.70%', '较 2026-09-02 市场广度改善']
          : ['上涨占比 62%，涨跌幅中位数 0.70%', '精确上一交易日广度快照缺失，无法判断改善或恶化'],
      },
      trend: {
        status: options.trendStatus ?? 'confirming',
        aboveMa20Count: options.aboveMa20Count ?? 4,
        belowMa20Count: options.belowMa20Count ?? 1,
        validCount: 5,
        reason: null,
        evidence: [`MA20 上方 ${options.aboveMa20Count ?? 4} 个，下方 ${options.belowMa20Count ?? 1} 个，有效 5 个`],
      },
      turnover: {
        status: options.turnoverStatus ?? 'confirming',
        medianAmountRatio5: 1.12,
        growthMedianAmountRatio5: options.growthMedianAmountRatio5 === undefined ? 1.1 : options.growthMedianAmountRatio5,
        volumeBackedAdvanceCount: options.volumeBackedAdvanceCount ?? 3,
        volumeBackedDeclineCount: options.volumeBackedDeclineCount ?? 0,
        validCount: 5,
        reason: null,
        evidence: [`5 日成交额比值有效 5 个，放量上涨 ${options.volumeBackedAdvanceCount ?? 3} 个，放量下跌 ${options.volumeBackedDeclineCount ?? 0} 个`],
      },
    },
    evidence: ['上证指数 +1.00%', '沪深300 +0.90%'],
    risks: options.risks ?? [],
  }
}

function chapter() {
  return {
    status: 'degraded',
    coverage: 0.8,
    combinationOverview: {
      strength: '指数分化',
      stage: '组合分化',
      capitalAcceptance: '量价分化',
      tradingMode: '保持观察',
      confidence: 'low',
      evidence: [],
    },
    summarySentence: '分化未定型，收盘位于MA20上方，60日区间中部，成交额为5日均值的1.10倍，量价平稳，保持观察。',
    dataGaps: [
      { field: 'slope', reason: 'insufficient-history' },
      { field: 'today', reason: 'missing-today' },
      { field: 'provider', reason: 'provider-failed' },
      { field: 'range', reason: 'not-computable' },
    ],
    assessment: { state: 'fixture', confidence: 'low', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
  }
}

async function mountScenario(assessment: SynchronizationAssessment) {
  const coreSummary = {
    synchronization: '核心旧同步结论',
    syncPattern: { code: assessment.patternCode, label: assessment.patternLabel, score: 4, evidence: assessment.evidence },
    synchronizationAssessment: { ...assessment, conclusion: '核心旧结论，不应继续显示。' },
    dominantTrend: '偏强',
    warnings: [],
  }
  const response = {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: Array.from({ length: 5 }, (_, index) => indexItem(index)),
    summary: coreSummary,
    chapter01: chapter(),
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.includes('chapter-01')
      ? {
          asOf: response.asOf,
          generatedAt: response.generatedAt,
          summary: { ...coreSummary, synchronizationAssessment: assessment },
          chapter01: chapter(),
        }
      : response,
  })))

  mountedWrapper = mount(App)
  await flushPromises()
  await flushPromises()
  return mountedWrapper
}

describe('index synchronization assessment', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    mountedWrapper?.unmount()
    mountedWrapper = null
    vi.unstubAllGlobals()
  })

  it('renders a confirmed synchronized rally and adopts the chapter summary', async () => {
    const wrapper = await mountScenario(synchronizationAssessment())

    expect(wrapper.text()).toContain('章节新结论：多数指数同步上涨且市场广度确认。')
    expect(wrapper.text()).not.toContain('核心旧结论，不应继续显示。')
    expect(wrapper.find('.synchronization-status.confirmed').text()).toBe('已确认')
    expect(wrapper.text()).toContain('较 2026-09-02：上涨占比 +7.0 个百分点，中位数 +0.20 个百分点')
  })

  it('keeps contradictory breadth visible for an index-only rally', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      status: 'contradicted',
      conclusion: '多数指数同步上涨，但多数个股偏弱，指数强势没有得到市场广度确认。',
      breadthStatus: 'contradicting',
      confidence: 'high',
      risks: ['指数与个股表现背离，不能按全面强势处理'],
    }))

    const breadthDimension = wrapper.find('.synchronization-dimension.contradicting')
    expect(breadthDimension.text()).toContain('市场广度')
    expect(breadthDimension.text()).toContain('反驳')
    expect(wrapper.text()).toContain('指数与个股表现背离')
  })

  it('distinguishes confirmed weight shelter from broad strength', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      patternCode: 'weight_shelter',
      patternLabel: '权重护盘',
      conclusion: '上证与沪深300偏强，而多数个股偏弱，权重护盘特征得到市场广度确认。',
      breadthStatus: 'confirming',
      trendStatus: 'neutral',
      turnoverStatus: 'neutral',
      risks: ['指数强于个股，不能将权重护盘定义为全面强势'],
    }))

    expect(wrapper.text()).toContain('权重护盘特征得到市场广度确认')
    expect(wrapper.text()).toContain('不能将权重护盘定义为全面强势')
  })

  it('renders unconfirmed growth leadership with a neutral turnover dimension', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      patternCode: 'growth_lead',
      patternLabel: '成长占优',
      status: 'unconfirmed',
      conclusion: '创业板与中证500相对占优，但广度或成交额仍处于中性区间，题材机会待继续验证。',
      confidence: 'low',
      turnoverStatus: 'neutral',
      growthMedianAmountRatio5: 0.9,
    }))

    expect(wrapper.find('.synchronization-status.unconfirmed').text()).toBe('待确认')
    expect(wrapper.text()).toContain('题材机会待继续验证')
    expect(wrapper.text()).toContain('0.90x')
  })

  it('renders confirmed growth leadership with breadth and turnover support', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      patternCode: 'growth_lead',
      patternLabel: '成长占优',
      conclusion: '创业板与中证500相对占优，市场广度和成交额共同确认成长及中小盘风险偏好改善。',
      growthMedianAmountRatio5: 1.16,
    }))

    expect(wrapper.text()).toContain('市场广度和成交额共同确认')
    expect(wrapper.text()).toContain('1.16x')
  })

  it('renders confirmed systemic decline and its three risk dimensions', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      patternCode: 'broad_weakness',
      patternLabel: '多数指数同步走弱',
      conclusion: '多数指数同步走弱，并伴随放量下跌、关键均线失守和下跌面扩大，风险偏好正在系统性下降。',
      breadthStatus: 'confirming',
      trendStatus: 'confirming',
      turnoverStatus: 'confirming',
      aboveMa20Count: 0,
      belowMa20Count: 5,
      volumeBackedAdvanceCount: 0,
      volumeBackedDeclineCount: 5,
      risks: ['弱势由广度、趋势和成交额共同确认，应优先控制风险'],
    }))

    expect(wrapper.text()).toContain('风险偏好正在系统性下降')
    expect(wrapper.text()).toContain('MA20 下方')
    expect(wrapper.text()).toContain('0 / 5')
    expect(wrapper.text()).toContain('弱势由广度、趋势和成交额共同确认')
  })

  it('keeps the missing previous-day breadth comparison visible', async () => {
    const wrapper = await mountScenario(synchronizationAssessment({
      comparisonAvailable: false,
      confidence: 'medium',
    }))

    expect(wrapper.find('.synchronization-comparison.insufficient').text()).toBe('精确上一交易日广度快照不可用')
    expect(wrapper.text()).toContain('精确上一交易日广度快照缺失，无法判断改善或恶化')
    expect(wrapper.text()).toContain('结论置信度中')
  })
})

describe('index combination matrix', () => {
  afterEach(() => {
    mountedWrapper?.unmount()
    mountedWrapper = null
    vi.unstubAllGlobals()
  })

  it('renders five rows, six columns, row linkage, summary, and all gap labels', async () => {
    const wrapper = await mountScenario(synchronizationAssessment())

    expect(wrapper.findAll('.combination-matrix tbody tr')).toHaveLength(5)
    expect(wrapper.findAll('.combination-matrix thead th')).toHaveLength(combinations.length + 1)
    await wrapper.findAll('.combination-matrix tbody tr')[3].trigger('click')
    expect(wrapper.text()).toContain('沪深300 · 选中行证据')
    expect(wrapper.text()).toContain('沪深300 evidence')
    expect(wrapper.text()).toContain('今日收束句')
    expect(wrapper.text()).toContain('历史窗口不足，暂无法计算分位')
    expect(wrapper.text()).toContain('当日行情尚未返回')
    expect(wrapper.text()).toContain('行情供应商请求失败')
    expect(wrapper.text()).toContain('当前数据在数学上不可计算')
  })
})

describe('chart lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    mountedWrapper?.unmount()
    mountedWrapper = null
    vi.unstubAllGlobals()
  })

  it('recreates charts after section loading replaces their DOM nodes', async () => {
    const assessment = synchronizationAssessment()
    const coreSummary = {
      synchronization: 'fixture',
      syncPattern: { code: assessment.patternCode, label: assessment.patternLabel, score: 4, evidence: assessment.evidence },
      synchronizationAssessment: assessment,
      dominantTrend: 'fixture',
      warnings: [],
    }
    const response = {
      asOf: '2026-09-03',
      generatedAt: '2026-09-03T16:00:00+08:00',
      indices: Array.from({ length: 5 }, (_, index) => indexItem(index)),
      summary: coreSummary,
      chapter01: chapter(),
    }
    let resolveChapter!: (value: unknown) => void
    const chapterResponse = new Promise((resolve) => { resolveChapter = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
      ok: true,
      json: async () => url.includes('chapter-01') ? chapterResponse : response,
    })))

    mountedWrapper = mount(App)
    await flushPromises()

    expect(mockEchartsInit).toHaveBeenCalledTimes(2)
    expect(mockEchartsSetOption).toHaveBeenCalledTimes(2)

    resolveChapter({
      asOf: response.asOf,
      generatedAt: response.generatedAt,
      summary: { ...coreSummary, synchronizationAssessment: assessment },
      chapter01: chapter(),
    })
    await flushPromises()
    await flushPromises()

    expect(mockEchartsDispose).toHaveBeenCalledTimes(2)
    expect(mockEchartsInit).toHaveBeenCalledTimes(4)
    expect(mockEchartsSetOption).toHaveBeenCalledTimes(4)
  })
})
