// @vitest-environment happy-dom

const { setOptionMock } = vi.hoisted(() => ({ setOptionMock: vi.fn() }))

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: setOptionMock, resize: vi.fn(), dispose: vi.fn() })),
}))

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document05SectorsPage from './Document05SectorsPage.vue'
import { routes } from '../../router/routes'
import { useMarketStore } from '../../stores/market'
import '../../styles.css'

function makeAnalysis(status = 'ok', asOf = '2026-09-03', withCandidate = true) {
  const traces = ['QTS-01-05-01', 'QTS-01-05-02', 'QTS-01-05-03', 'QTS-01-05-04', 'QTS-01-05-05'].map((ruleId, index) => ({
    ruleId, value: index === 1 ? 4 : 0.8, percentile: index === 1 ? 0.8 : 0.85, score: 80, status,
    weight: 0.2, originalWeight: 0.2, normalizedWeight: 0.2, observations: status === 'insufficient' ? 20 : 120,
    requiredObservations: 60, windowDays: 250, missingReason: status === 'insufficient' ? 'history-gap' : null,
    sampleDates: [asOf], actualDateRange: [asOf], gaps: status === 'insufficient' ? ['2026-08-01'] : [], raw: {},
  }))
  const candidate = {
    industryId: '801010', displayName: '农林牧渔', stage: 'mainline-candidate', totalScore: 82,
    coreScores: { persistence: 80, breadth: 75, turnover: 90 }, ruleTraces: traces,
    crowdingRisk: false, vetoes: [], confirmationStreak: 2,
    internalStructure: {
      effectiveMemberCount: 12, advancingCount: 8, decliningCount: 3, flatCount: 1,
      limitUpCount: 2, limitDownCount: 0, topByTurnover: [{ name: '样本一' }], topByReturn: [{ name: '样本二' }],
      topSecurityTurnoverContribution: 0.22, diffusionRatio: 0.67,
    },
  }
  return {
    asOf, status, quality: {
      status, confidence: status === 'insufficient' ? 'insufficient' : 'medium', coverage: status === 'insufficient' ? 0.2 : 0.8,
      asOf, requiredObservations: 60, availableObservations: status === 'insufficient' ? 20 : 120, warnings: [], missingInputs: [],
    },
    history: { requiredObservations: 60, windowDays: 250, validObservations: status === 'insufficient' ? 20 : 120, actualDateRange: [asOf], gaps: [], quality: null },
    metricTraces: traces, candidates: withCandidate && status !== 'insufficient' ? [candidate] : [],
    validation: {
      candidateIndustry: withCandidate && status !== 'insufficient' ? '801010' : null,
      candidateName: withCandidate && status !== 'insufficient' ? '农林牧渔' : null,
      stage: withCandidate && status !== 'insufficient' ? 'mainline-candidate' : 'insufficient',
      persistenceEvidence: '5 日与 20 日均有效', breadthEvidence: '宽度 P75', turnoverEvidence: '近 5 日 4 天进入前 20%',
      internalStructure: '扩散比例 67%', target: '候选板块核心成员', confirmationCondition: '三项核心分数均 ≥ 60，且连续三日', invalidationCondition: '任一核心分数 < 60 或承接低于 50%',
    },
    risk: { crowdingRisk: false }, lineage: { calculationVersion: 'sector-continuity-v1' }, latestAttempt: null, warnings: [],
  }
}

function ranking(asOf = '2026-09-03') {
  return {
    state: 'ok',
    asOf,
    revisionId: 'catalog-r7',
    quality: { dataset: 'industry-ranking', source: 'fuyao', provider: 'fuyao', status: 'ok', observations: 4, asOf, warnings: [] },
    rows: [
      { tag: 'industry', rank: 1, thscode: '885001.TI', name: '农林牧渔', changePct: 2.35, volume: 120000000, turnover: 1500000000, catalogRevision: 'catalog-r7', asOf },
      { tag: 'industry', rank: 2, thscode: '885002.TI', name: '半导体', changePct: -1.2, volume: 80000000, turnover: 900000000, catalogRevision: 'catalog-r7', asOf },
      { tag: 'cn_concept', rank: 1, thscode: '886001.TI', name: '人工智能', changePct: 1.5, volume: 60000000, turnover: 700000000, catalogRevision: 'catalog-r7', asOf },
      { tag: 'region', rank: 1, thscode: '887001.TI', name: '上海板块', changePct: 0.5, volume: null, turnover: 500000000, catalogRevision: 'catalog-r7', asOf },
      { tag: 'tszs', rank: 1, thscode: '888001.TI', name: '特色样本', changePct: 0.2, volume: 30000000, turnover: 400000000, catalogRevision: 'catalog-r7', asOf },
    ],
  }
}

function breadth(asOf = '2026-09-03') {
  return {
    state: 'partial',
    asOf,
    quality: { dataset: 'sector-breadth', source: 'fuyao+tdx', status: 'partial', observations: 1, asOf, warnings: ['一个成员缺少 MA20'] },
    rows: [{
      thscode: '885001.TI', name: '农林牧渔', tag: 'industry', asOf,
      selectionReasons: ['industry-top-10', 'user-selected'],
      memberCount: 12, validDirectionCount: 11, advanceCount: 8, declineCount: 2, flatCount: 1,
      advanceRatio: 8 / 11, advanceDeclineSpreadRatio: 6 / 11, medianChangePct: 0.8,
      validMa20Count: 10, closeAboveMa20Count: 7, ma20Breadth: 0.7,
      limitUpCount: 2, limitDownCount: 0,
      topByTurnover: [{ securityId: '000001.SZ', name: '样本一', value: 100000000 }],
      topByGain: [{ securityId: '000002.SZ', name: '样本二', value: 9.8 }],
      maxMemberTurnoverContribution: 0.22, diffusionRate: 0.78,
      quality: 'partial', warnings: ['一个成员缺少 MA20'], lineage: { close: 'fuyao', turnover: 'tdx' },
    }],
  }
}

function makeResponse(options: {
  rankingAsOf?: string
  breadthAsOf?: string
  analysis?: Record<string, unknown> | null
} = {}) {
  const asOf = '2026-09-03'
  return {
    asOf,
    generatedAt: `${asOf}T16:00:00+08:00`,
    indices: [],
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'degraded',
      coverage: 0.75,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
      industryRanking: ranking(options.rankingAsOf),
      sectorTurnover: {
        state: 'ok', asOf,
        rows: [],
        quality: { dataset: 'sector-turnover', source: 'fuyao', status: 'ok', observations: 5, asOf, warnings: [] },
      },
      sectorBreadth: breadth(options.breadthAsOf),
      sectorAnalysis: options.analysis === undefined ? makeAnalysis() : options.analysis,
    },
  }
}

async function mountPage(options: Parameters<typeof makeResponse>[0] = {}) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse(options) as never
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/05')
  await router.isReady()
  const wrapper = mount(Document05SectorsPage, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

function tab(wrapper: Awaited<ReturnType<typeof mountPage>>, label: string) {
  return wrapper.findAll('.sector-view-tabs button').find((button) => button.text() === label)!
}

describe('Document05SectorsPage', () => {
  beforeEach(() => {
    setOptionMock.mockReset()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders all four views and a searchable four-classification THS ranking', async () => {
    const wrapper = await mountPage()

    expect(wrapper.findAll('.sector-view-tabs button').map((button) => button.text())).toEqual([
      '排名', '板块宽度', '量价 K 线', '申万持续性',
    ])
    expect(wrapper.text()).toContain('THS provider observation 与申万 canonical analysis 独立展示')
    expect(wrapper.text()).toContain('农林牧渔')
    expect(wrapper.text()).toContain('885001.TI')
    expect(wrapper.text()).toContain('+2.35%')
    expect(wrapper.text()).toContain('-1.20%')
    expect(wrapper.text()).toContain('目录版本catalog-r7')

    await wrapper.find('input[type="search"]').setValue('半导体')
    expect(wrapper.find('.ths-ranking-scroll').text()).toContain('半导体')
    expect(wrapper.find('.ths-ranking-scroll').text()).not.toContain('农林牧渔')

    await wrapper.find('select').setValue('cn_concept')
    expect(wrapper.text()).toContain('本地排名不足')
    await wrapper.find('input[type="search"]').setValue('')
    expect(wrapper.find('.ths-ranking-scroll').text()).toContain('人工智能')
  })

  it('renders formula-complete current-day breadth and source warnings', async () => {
    const wrapper = await mountPage()
    await tab(wrapper, '板块宽度').trigger('click')

    expect(wrapper.text()).toContain('板块内部宽度')
    expect(wrapper.text()).toContain('上涨 / 下跌 / 平盘8 / 2 / 1')
    expect(wrapper.text()).toContain('上涨占比72.7%')
    expect(wrapper.text()).toContain('差率 54.5%')
    expect(wrapper.text()).toContain('MA20 宽度70.0%')
    expect(wrapper.text()).toContain('涨停 / 跌停2 / 0')
    expect(wrapper.text()).toContain('扩散率78.0%')
    expect(wrapper.text()).toContain('最高单股贡献 22.0%')
    expect(wrapper.text()).toContain('样本一')
    expect(wrapper.text()).toContain('样本二')
    expect(wrapper.text()).toContain('industry-top-10、user-selected')
    expect(wrapper.text()).toContain('一个成员缺少 MA20')
  })

  it('keeps THS observation separate from Shenwan continuity evidence', async () => {
    const wrapper = await mountPage()
    await tab(wrapper, '申万持续性').trigger('click')

    expect(wrapper.text()).toContain('申万一级 · 连续性分析')
    expect(wrapper.text()).toContain('第 05 章五项规则证据')
    expect(wrapper.text()).toContain('QTS-01-05-01')
    expect(wrapper.text()).toContain('主线候选')
    expect(wrapper.text()).toContain('成交排名靠前')
    expect(wrapper.text()).toContain('下一交易日只验证：分歧后候选板块核心成员能否承接。')
    expect(wrapper.text()).toContain('确认条件')
    expect(wrapper.text()).not.toContain('catalog-r7')
  })

  it('does not display cross-date THS or Shenwan evidence', async () => {
    const wrapper = await mountPage({
      rankingAsOf: '2026-09-02',
      breadthAsOf: '2026-09-02',
      analysis: makeAnalysis('ok', '2026-09-02'),
    })

    expect(wrapper.text()).toContain('排名日期不一致')
    expect(wrapper.find('.ths-ranking-scroll').exists()).toBe(false)
    await tab(wrapper, '板块宽度').trigger('click')
    expect(wrapper.text()).toContain('宽度日期不一致')
    await tab(wrapper, '申万持续性').trigger('click')
    expect(wrapper.text()).toContain('分析日期与所选日期不一致')
    expect(wrapper.find('.sector-metric-grid').exists()).toBe(false)
  })

  it('reads local K-lines, renders candle/volume/turnover, and backfills only after explicit action', async () => {
    const bars = {
      thscode: '885001.TI',
      requestedStart: '2025-09-03',
      requestedEnd: '2026-09-03',
      coverage: { firstDate: '2026-09-01', lastDate: '2026-09-03', storedRows: 2, gaps: ['2025-09-03/2026-08-31'] },
      items: [
        { tradingDate: '2026-09-02', open: 100, high: 103, low: 99, close: 102, volume: 120000, turnover: 880000000, quality: 'ok', source: 'fuyao', sourceRevision: 'history-r1', warnings: [] },
        { tradingDate: '2026-09-03', open: 102, high: 104, low: 101, close: 103, volume: 130000, turnover: 920000000, quality: 'ok', source: 'fuyao', sourceRevision: 'history-r1', warnings: [] },
      ],
      page: 1, pageSize: 1500, total: 2,
    }
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/ths/sectors/885001.TI/bars')) return { ok: true, json: async () => bars }
      if (url === '/api/market-environment/ths/turnover/backfills' && init?.method === 'POST') {
        return { ok: true, json: async () => ({ runId: 'backfill-r1', status: 'queued' }) }
      }
      if (url === '/api/market-environment/ths/operations/backfill-r1') {
        return { ok: true, json: async () => ({
          runId: 'backfill-r1', kind: 'turnover-backfill', status: 'running',
          progress: { completed: 1, total: 2, failed: 0, conflicts: 0 }, warning: null, checkpoints: [],
        }) }
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountPage()
    await tab(wrapper, '量价 K 线').trigger('click')
    await flushPromises()

    const getCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/ths/sectors/885001.TI/bars'))
    expect(getCall?.[0]).toBe('/api/market-environment/ths/sectors/885001.TI/bars?start_date=2025-09-03&end_date=2026-09-03&page=1&page_size=1500')
    expect(fetchMock.mock.calls.some((call) => call[0] === '/api/market-environment/ths/turnover/backfills')).toBe(false)
    expect(wrapper.text()).toContain('实际覆盖2026-09-01 至 2026-09-03')
    expect(wrapper.text()).toContain('显式回填缺口')
    expect(wrapper.find('.sector-turnover-chart').exists()).toBe(true)

    const option = setOptionMock.mock.calls.at(-1)?.[0] as {
      legend: { textStyle: { fontSize: number } }
      tooltip: { textStyle: { fontSize: number } }
      xAxis: Array<{ axisLabel: { fontSize: number } }>
      yAxis: Array<{ axisLabel: { fontSize: number } }>
      series: Array<{ type: string; name: string }>
    }
    expect(option.series.map((series) => [series.name, series.type])).toEqual([
      ['板块 K 线', 'candlestick'], ['成交量', 'bar'], ['成交额', 'bar'],
    ])
    expect(option.legend.textStyle.fontSize).toBeGreaterThanOrEqual(14)
    expect(option.tooltip.textStyle.fontSize).toBeGreaterThanOrEqual(14)
    expect(option.xAxis.every((axis) => axis.axisLabel.fontSize >= 14)).toBe(true)
    expect(option.yAxis.every((axis) => axis.axisLabel.fontSize >= 14)).toBe(true)

    await wrapper.find('button.command-button').trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find((call) => call[0] === '/api/market-environment/ths/turnover/backfills')
    expect(JSON.parse((post?.[1] as RequestInit).body as string)).toEqual({
      thscodes: ['885001.TI'], startDate: '2025-09-03', endDate: '2026-09-03',
    })
    expect(wrapper.text()).toContain('回填任务backfill-r1')
    expect(wrapper.text()).toContain('状态执行中')
    expect(wrapper.text()).toContain('进度1 / 2')
  })

  it('keeps visible text at least 14px and preserves narrow-layout containers', async () => {
    window.innerWidth = 390
    window.dispatchEvent(new Event('resize'))
    const wrapper = await mountPage()

    expect(wrapper.find('.sector-view-tabs').exists()).toBe(true)
    expect(wrapper.find('.ths-ranking-scroll').exists()).toBe(true)
    for (const node of wrapper.findAll('p, span, strong, button, th, td, label, input, select').filter((item) => item.isVisible())) {
      const fontSize = Number.parseFloat(getComputedStyle(node.element).fontSize)
      if (Number.isFinite(fontSize) && fontSize > 0) expect(fontSize).toBeGreaterThanOrEqual(14)
    }
  })
})
