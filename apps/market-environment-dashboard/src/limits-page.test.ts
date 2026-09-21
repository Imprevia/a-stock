// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import Document03LimitsPage from './pages/dashboard/Document03LimitsPage.vue'
import { routes } from './router/routes'
import { useMarketStore } from './stores/market'

vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })) }))

let wrapper: VueWrapper | null = null

const quality = {
  dataset: 'limits', source: 'fixture-snapshot', provider: 'fixture', status: 'ok', observations: 42,
  asOf: '2026-09-10', cacheState: 'fresh', snapshotFetchedAt: '2026-09-10T16:10:00+08:00', warnings: [],
}

const baseChapter = {
  status: 'degraded', coverage: 0.2,
  combinationOverview: { strength: '数据不足', stage: '数据不足', capitalAcceptance: '数据不足', tradingMode: '保持观察', confidence: 'insufficient', evidence: [] },
  assessment: { state: 'insufficient', confidence: 'insufficient', evidence: [], risks: [], nextConfirmation: null, invalidation: null },
}

function coreResponse() {
  return {
    asOf: '2026-09-10', generatedAt: '2026-09-10T16:12:00+08:00', indices: [],
    summary: { synchronization: '数据不足', dominantTrend: '数据不足', warnings: [] },
    chapter01: baseChapter,
  }
}

function completeLimits() {
  const metricQuality = { status: 'ok', reason: null, observations: 20, asOf: '2026-09-10', source: 'fixture', warnings: [] }
  const detailRow = (index: number, poolType = 'limit_up') => ({
    securityId: `security-${index}`,
    thscode: `600${String(index).padStart(3, '0')}.SH`,
    code: `600${String(index).padStart(3, '0')}`,
    exchange: 'SH',
    name: index === 5 ? '目标证券' : `证券${index}`,
    poolType,
    isSt: false,
    isNew: false,
    listingDate: '2020-01-01',
    closePrice: index === 5 ? null : 10 + index,
    changePct: index === 5 ? null : 10,
    streakDays: index === 5 ? null : 1,
    limitUpTime: null,
    limitUpReason: index === 5 ? null : '人工智能',
    sealMoney: null,
    maxSealMoney: null,
    firstLimitTime: null,
    lastLimitTime: null,
    openTimes: null,
    turnoverRatioPct: null,
    turnover: null,
    source: 'fuyao',
    rowQuality: index === 5 ? 'degraded' : 'ok',
    warnings: index === 5 ? ['字段不完整，保留集合成员'] : [],
  })
  return {
    limitUpCount: 64, limitDownCount: 5, failedLimitUpCount: 15, failedLimitUpRatio: 0.2308, maxStreak: 6,
    todayPromoted: 8, yesterdayLimitUpEligible: 20, promotionRatio: 0.4,
    promotionSampleAsOf: '2026-09-10', promotionPreviousAsOf: '2026-09-09',
    promotionSampleRule: '前一交易日合资格收盘涨停 -> 当日同证券收盘涨停', promotionRuleVersion: 'limits-promotion-v1',
    promotionQuality: metricQuality,
    fieldQuality: { todayPromoted: metricQuality, yesterdayLimitUpEligible: metricQuality, promotionRatio: metricQuality },
    ladder: [
      { tier: 'first', label: '首板', count: 38, observations: 38, quality: metricQuality },
      { tier: 'four_plus', label: '四板以上', count: 4, observations: 4, quality: metricQuality },
    ],
    stratifications: [
      { dimension: 'regime', key: 'main-board', label: '主板', count: 31, observations: 31, quality: metricQuality },
      { dimension: 'sector', key: 'ai', label: '人工智能', count: 12, observations: 12, quality: metricQuality },
    ],
    history: {
      points: [{ asOf: '2026-09-10', limitUpCount: 64, limitDownCount: 5, failedLimitUpRatio: 0.2308, promotionRatio: 0.4, maxStreak: 6, quality: metricQuality }],
      validObservations: 58, requiredObservations: 60, windowDays: 250, percentile250: { limitUpCount: 0.7, limitDownCount: 0.2, failedLimitUpRatio: 0.4, promotionRatio: 0.55, maxStreak: 0.8 }, quality: { ...metricQuality, status: 'insufficient' },
    },
    ruleEvidence: [{ ruleId: 'QTS-01-03-04', status: 'research', score: 62.5, weight: 0.25, calibrationStatus: 'needs-backtest', evidence: ['晋级率 40.00%'], missingInputs: [] }],
    riskEvidence: [{ code: 'limit-down-spread', label: '连续跌停风险', status: 'insufficient', value: null, evidence: [] }],
    securityDetails: {
      limitUp: { total: 21, rows: Array.from({ length: 21 }, (_, index) => detailRow(index)), quality: { ...metricQuality, observations: 21 } },
      limitDown: { total: 1, rows: [detailRow(90, 'limit_down')], quality: { ...metricQuality, observations: 1 } },
      failedLimitUp: { total: 1, rows: [detailRow(91, 'failed_limit_up')], quality: { ...metricQuality, observations: 1 } },
      promoted: { total: 1, rows: [detailRow(92, 'limit_up')], quality: { ...metricQuality, observations: 1 } },
    },
    confirmation: '观察晋级率能否继续高于 40%', invalidation: '炸板率快速升高则失效', state: '分歧修复', quality,
  }
}

async function mountLimits(limits: Record<string, unknown>, refreshFails = false) {
  let chapterCalls = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (!url.includes('chapter-01')) return { ok: true, json: async () => coreResponse() }
    chapterCalls += 1
    if (refreshFails && chapterCalls > 1) return { ok: false, status: 502, json: async () => ({ detail: 'fixture refresh failed' }) }
    return { ok: true, json: async () => ({ asOf: '2026-09-10', generatedAt: '2026-09-10T16:12:00+08:00', chapter01: { ...baseChapter, limits } }) }
  }))
  setActivePinia(createPinia())
  const market = useMarketStore()
  await market.loadCore()
  await flushPromises()
  await market.loadSection('limits')
  await flushPromises()
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/dashboard/03')
  await router.isReady()
  wrapper = mount(Document03LimitsPage, {
    global: { plugins: [router] },
    props: {
      onRefreshSection: () => void market.loadSection('limits', true),
    },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('第 03 页涨跌停证据', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(() => { wrapper?.unmount(); wrapper = null; vi.unstubAllGlobals() })

  it('直接展示完整晋级、梯队、分层、历史和规则证据', async () => {
    const view = await mountLimits(completeLimits())
    expect(view.text()).toContain('炸板率23.08%')
    expect(view.text()).toContain('晋级率40.00%')
    expect(view.text()).toContain('今日晋级8')
    expect(view.text()).toContain('昨日合格样本20')
    expect(view.text()).toContain('四板以上')
    expect(view.text()).toContain('人工智能')
    expect(view.text()).toContain('QTS-01-03-04')
    expect(view.text()).toContain('待回测')
    expect(view.text()).toContain('58 / 60')
    expect(view.text()).not.toContain('NaN')
    expect(view.text()).not.toContain('undefined')
  })

  it('兼容旧五字段响应并明确新证据不足', async () => {
    const view = await mountLimits({ limitUpCount: 20, limitDownCount: 3, failedLimitUpCount: 2, failedLimitUpRatio: 0.1, maxStreak: 2, state: '旧响应', quality })
    expect(view.text()).toContain('涨停20')
    expect(view.text()).toContain('晋级率--')
    expect(view.text()).toContain('梯队证据不足')
    expect(view.text()).toContain('分层证据不足')
    expect(view.text()).toContain('规则输入不足')
  })

  it('缺失快照不伪造零值', async () => {
    const view = await mountLimits({ limitUpCount: null, limitDownCount: null, failedLimitUpCount: null, failedLimitUpRatio: null, maxStreak: null, state: '数据不足', quality: { ...quality, status: 'missing', observations: 0, warning: '精确日期快照缺失' } })
    expect(view.text()).toContain('缺失')
    expect(view.text()).toContain('精确日期快照缺失')
    expect(view.text()).toContain('不代表 0')
    expect(view.text()).not.toContain('涨停0')
  })

  it('局部刷新失败时保留同日期旧证据', async () => {
    const view = await mountLimits(completeLimits(), true)
    await view.get('button[aria-label="刷新涨跌停证据"]').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('涨停64')
    expect(view.text()).toContain('刷新失败，继续显示同日期最后一次证据')
    expect(view.text()).toContain('fixture refresh failed')
  })

  it('支持四组切换和 20 行本地分页', async () => {
    const view = await mountLimits(completeLimits())
    expect(view.findAll('.limit-security-tabs [role="tab"]')).toHaveLength(4)
    expect(view.findAll('.limit-security-table tbody tr')).toHaveLength(20)

    await view.get('button[aria-label="下一页"]').trigger('click')
    expect(view.text()).toContain('第 2 / 2 页')
    expect(view.findAll('.limit-security-table tbody tr')).toHaveLength(1)
    expect(view.text()).toContain('600020.SH')

    await view.findAll('.limit-security-tabs [role="tab"]')[1].trigger('click')
    expect(view.text()).toContain('第 1 / 1 页')
    expect(view.find('.limit-security-table tbody tr').text()).toContain('600090.SH')
  })

  it('按代码或名称搜索并保留 null 与行级 warning', async () => {
    const view = await mountLimits(completeLimits())
    await view.get('.limit-security-search input').setValue('目标证券')

    const rows = view.findAll('.limit-security-table tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('600005.SH')
    expect(rows[0].text()).toContain('目标证券')
    expect(rows[0].text()).toContain('--')
    expect(rows[0].text()).toContain('降级')
    expect(rows[0].text()).toContain('字段不完整，保留集合成员')
  })

  it('在 390px 视口只允许明细表容器局部横向滚动', async () => {
    const view = await mountLimits(completeLimits())
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 844 })
    window.dispatchEvent(new Event('resize'))
    await flushPromises()

    expect((view.element as HTMLElement).scrollWidth).toBeLessThanOrEqual(390)
    expect(view.find('.limit-security-table-scroll').exists()).toBe(true)
    expect(view.find('.limit-security-table').exists()).toBe(true)
  })
})
