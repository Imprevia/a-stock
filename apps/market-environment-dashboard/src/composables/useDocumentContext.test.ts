// @vitest-environment happy-dom

import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketStore } from '../stores/market'
import { useDocumentContext } from './useDocumentContext'

function indexItem(position: number) {
  return {
    code: `index-${position}`,
    name: `指数${position}`,
    representative: 'fixture',
    // Force all five indices to have a positive changePct so they align with
    // the fixture breadth medianReturn (>0) and the consistency summary can
    // report '5 / 5 强一致'.
    changePct: (position + 1) / 10,
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
      key: 'rotation',
      state: '震荡轮动',
      matched: true,
      tone: 'neutral',
      evidence: [`指数${position} evidence`],
      tradingMode: '轮动应对',
    },
    history: [],
    dataQuality: { source: 'fixture', isStale: false, warning: null },
    dataGaps: [],
  }
}

function makeResponse() {
  return {
    asOf: '2026-09-03',
    generatedAt: '2026-09-03T16:00:00+08:00',
    indices: Array.from({ length: 5 }, (_, index) => indexItem(index)),
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'ok',
      coverage: 0.8,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      breadth: {
        advanceCount: 3000,
        declineCount: 2000,
        flatCount: 500,
        validCount: 5500,
        advanceRatio: 0.55,
        declineRatio: 0.36,
        advanceDeclineSpread: 0.18,
        medianReturn: 0.5,
        state: 'ok',
        quality: { dataset: 'breadth', source: 'fixture', status: 'ok', warnings: [] },
        momentum: 0.05,
        indexConsistent: true,
        widthLabel: '同向增强',
        widthLabelReason: 'fixture',
        advanceRatioPercentile: 0.55,
        medianReturnPercentile: 0.6,
        spreadPercentile: 0.65,
        momentumPercentile: 0.5,
        history: { points: [], validObservations: 60, requiredObservations: 60, windowDays: 250, coverage: 0.24, percentile250: { advanceRatio: 0.78, medianReturn: 0.55, advanceDeclineSpread: 0.65, momentum: 0.7 }, quality: { status: 'ok', reason: null, observations: 60, asOf: '2026-09-03', source: 'fixture', warnings: [] } },
      },
      limits: {
        limitUpCount: 64,
        limitDownCount: 5,
        failedLimitUpCount: 15,
        failedLimitUpRatio: 0.23,
        maxStreak: 6,
        todayPromoted: 8,
        yesterdayLimitUpEligible: 20,
        promotionRatio: 0.4,
        promotionSampleAsOf: '2026-09-03',
        promotionPreviousAsOf: '2026-09-02',
        promotionSampleRule: 'fixture',
        promotionRuleVersion: 'fixture',
        promotionQuality: { status: 'ok', reason: null, observations: 20, asOf: '2026-09-03', source: 'fixture', warnings: [] },
        fieldQuality: { todayPromoted: { status: 'ok', reason: null, observations: 20, asOf: '2026-09-03', source: 'fixture', warnings: [] } },
        ladder: [{ tier: 'first', label: '首板', count: 38, observations: 38, quality: { status: 'ok', reason: null, observations: 38, asOf: '2026-09-03', source: 'fixture', warnings: [] } }],
        stratifications: [{ dimension: 'regime', key: 'main-board', label: '主板', count: 31, observations: 31, quality: { status: 'ok', reason: null, observations: 31, asOf: '2026-09-03', source: 'fixture', warnings: [] } }],
        history: { points: [{ asOf: '2026-09-03', limitUpCount: 64, limitDownCount: 5, failedLimitUpRatio: 0.23, promotionRatio: 0.4, maxStreak: 6, quality: { status: 'ok', reason: null, observations: 60, asOf: '2026-09-03', source: 'fixture', warnings: [] } }], validObservations: 58, requiredObservations: 60, windowDays: 250, coverage: 0.97, percentile250: { limitUpCount: 0.7, limitDownCount: 0.2, failedLimitUpRatio: 0.4, promotionRatio: 0.55, maxStreak: 0.8 }, quality: { status: 'ok', reason: null, observations: 58, asOf: '2026-09-03', source: 'fixture', warnings: [] } },
        state: '分歧修复',
        quality: { dataset: 'limits', source: 'fixture', provider: 'fixture', status: 'ok', observations: 42, asOf: '2026-09-03', cacheState: 'fresh', snapshotFetchedAt: '2026-09-03T16:10:00+08:00', warnings: [] },
      },
    },
  }
}

describe('useDocumentContext — breadth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('exposes 5 breadth rule rows with percentile bands and weight labels', () => {
    const market = useMarketStore()
    market.data = makeResponse() as never
    const ctx = useDocumentContext()
    const rows = ctx.breadthRuleRows.value
    expect(rows).toHaveLength(5)
    expect(rows[0]).toMatchObject({
      id: 'QTS-01-02-01',
      title: '上涨占比',
      weightLabel: '30%',
    })
    expect(rows[4]).toMatchObject({
      id: 'QTS-01-02-05',
      title: '指数广度一致',
      weightLabel: '10%',
      scoreLabel: '100 分',
    })
  })

  it('computes breadthConsistencySummary from indexConsistent values', () => {
    const market = useMarketStore()
    market.data = makeResponse() as never
    const ctx = useDocumentContext()
    expect(ctx.breadthConsistencySummary.value).toMatch(/^5 \/ 5 强一致$/)
  })

  it('formats breadthVerification with median floor derived from advanceRatio', () => {
    const market = useMarketStore()
    market.data = makeResponse() as never
    const ctx = useDocumentContext()
    const v = ctx.breadthVerification.value
    expect(v.confirm).toContain('60%')
    expect(v.invalidate).toContain('40%')
    expect(v.consistencyHint).toBe('一致')
  })

  it('deduplicates breadthWarnings', () => {
    const market = useMarketStore()
    const response = makeResponse() as any
    response.chapter01.breadth.quality.warnings = ['w1', 'w1', 'w2']
    market.data = response
    const ctx = useDocumentContext()
    expect(ctx.breadthWarnings.value).toEqual(['w1', 'w2'])
  })
})

describe('useDocumentContext — limits', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('groups limitStratifications by dimension with localised labels', () => {
    const market = useMarketStore()
    market.data = makeResponse() as never
    const ctx = useDocumentContext()
    expect(ctx.limitStratifications.value).toEqual([
      { label: '涨跌幅制度', rows: expect.arrayContaining([expect.objectContaining({ key: 'main-board' })]) },
    ])
  })

  it('reports empty promotionGap when promotionRatio is present', () => {
    const market = useMarketStore()
    market.data = makeResponse() as never
    const ctx = useDocumentContext()
    expect(ctx.promotionGap.value).toBe('')
  })

  it('maps known reason codes to human-readable promotionGap text', () => {
    const market = useMarketStore()
    const response = makeResponse() as any
    response.chapter01.limits.promotionRatio = null
    response.chapter01.limits.promotionQuality.reason = 'zero-denominator'
    market.data = response
    const ctx = useDocumentContext()
    expect(ctx.promotionGap.value).toContain('昨日合格样本为 0')
  })

  it('aggregates limitWarnings across quality, promotion and field sources', () => {
    const market = useMarketStore()
    const response = makeResponse() as any
    response.chapter01.limits.quality.warnings = ['a']
    response.chapter01.limits.promotionQuality.warnings = ['b']
    response.chapter01.limits.fieldQuality.todayPromoted.warnings = ['a', 'c']
    market.data = response
    const ctx = useDocumentContext()
    expect(ctx.limitWarnings.value).toEqual(['a', 'b', 'c'])
  })
})

describe('useDocumentContext — label dictionaries', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('qualityLabel returns the localised label or 数据不足', () => {
    const ctx = useDocumentContext()
    expect(ctx.qualityLabel({ status: 'ok', warnings: [] } as never)).toBe('正常')
    expect(ctx.qualityLabel({ status: 'missing', warnings: [] } as never)).toBe('缺失')
    expect(ctx.qualityLabel(undefined)).toBe('数据不足')
  })

  it('qualityTone classifies ok / fallback / missing correctly', () => {
    const ctx = useDocumentContext()
    expect(ctx.qualityTone({ status: 'ok', warnings: [] } as never)).toBe('ok')
    expect(ctx.qualityTone({ status: 'partial', warnings: [] } as never)).toBe('fallback')
    expect(ctx.qualityTone({ status: 'missing', warnings: [] } as never)).toBe('missing')
  })

  it('reasonLabel maps current-breadth-unavailable to 当日市场广度不可用', () => {
    const ctx = useDocumentContext()
    expect(ctx.reasonLabel('current-breadth-unavailable')).toBe('当日市场广度不可用')
    expect(ctx.reasonLabel(null)).toBe('')
  })

  it('environmentLabel maps trend/rotation/retreat/mixed/insufficient', () => {
    const ctx = useDocumentContext()
    expect(ctx.environmentLabel('trend')).toBe('趋势')
    expect(ctx.environmentLabel('insufficient')).toBe('数据不足')
    expect(ctx.environmentLabel('unknown')).toBe('unknown')
  })

  it('gapLabel returns 数据不足 for unknown reasons', () => {
    const ctx = useDocumentContext()
    expect(ctx.gapLabel('insufficient-history')).toContain('历史窗口不足')
    expect(ctx.gapLabel('something-new')).toBe('数据不足')
  })

  it('formatRatioDelta and formatReturnDelta handle null / negative values', () => {
    const ctx = useDocumentContext()
    expect(ctx.formatRatioDelta(null)).toBe('--')
    expect(ctx.formatRatioDelta(0.123)).toMatch(/^\+12\.3 个百分点$/)
    expect(ctx.formatRatioDelta(-0.05)).toMatch(/^-5\.0 个百分点$/)
    expect(ctx.formatReturnDelta(0.5)).toMatch(/^\+0\.50 个百分点$/)
  })
})