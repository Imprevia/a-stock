// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DataCollectionView from './data-collection-view.vue'

let wrapper: VueWrapper | null = null

const DATASETS = [
  'core',
  'breadth',
  'limits',
  'industry-ranking',
  'sector-turnover',
  'sector-breadth',
  'activeDirection',
] as const

function dataset(
  name: typeof DATASETS[number],
  detail?: Record<string, unknown>,
  qualityOverride?: Record<string, unknown> | null,
  attemptStatus?: string,
) {
  const available = ['limits', 'industry-ranking', 'sector-turnover', 'activeDirection'].includes(name)
  return {
    dataset: name,
    available,
    source: name === 'activeDirection' ? 'tdx-daily-package-derived' : 'fixture',
    observations: name === 'limits' ? 64 : name === 'activeDirection' ? 30 : available ? 40 : 0,
    lastSuccessAt: available ? '2026-09-10T16:00:00+08:00' : null,
    settled: true,
    refreshWarning: null,
    quality: qualityOverride ?? (name === 'activeDirection'
      ? { status: 'fallback-derived', rankingMethod: 'local-turnover-desc-identity-asc', industryMappingCoverage: 0.5 }
      : null),
    latestAttempt: attemptStatus || name === 'limits' ? {
      taskId: `task-${name}`,
      runId: 'run-1',
      status: attemptStatus ?? 'failed-retained',
      source: 'fixture',
      observations: available ? 40 : 0,
      warning: attemptStatus === 'blocked' ? '依赖 industry-ranking 未完成' : name === 'limits' ? '上次刷新失败，保留旧值' : null,
      queuedAt: null,
      startedAt: null,
      completedAt: null,
      durationMs: 100,
      settled: true,
    } : null,
    activeTaskId: null,
    collectionAllowed: true,
    restriction: null,
    coreIndices: [],
    detail,
  }
}

function allDatasets(overrides: Partial<Record<typeof DATASETS[number], ReturnType<typeof dataset>>> = {}) {
  return DATASETS.map((name) => overrides[name] ?? dataset(name))
}

function statusResponse(overrides: Record<string, unknown> = {}) {
  return {
    asOf: '2026-09-15',
    manualRefreshEnabled: true,
    datasets: allDatasets(),
    ...overrides,
  }
}

describe('data collection view', () => {
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    vi.unstubAllGlobals()
  })

  it('shows limits sample dates, exclusions and promotion dependency on expansion', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      asOf: '2026-09-10',
      datasets: allDatasets({
        limits: dataset('limits', {
          sampleAsOf: '2026-09-10', previousAsOf: '2026-09-09', excludedCount: 7,
          promotionQuality: 'insufficient', promotionDependency: '需要精确相邻交易日和规范证券身份', warnings: ['缺少收盘状态'],
        }),
      }),
    }) })))
    wrapper = mount(DataCollectionView)
    await flushPromises()
    await wrapper.find('button[aria-label="展开涨跌停生态"]').trigger('click')

    expect(wrapper.text()).toContain('当前样本日期')
    expect(wrapper.text()).toContain('2026-09-10')
    expect(wrapper.text()).toContain('排除样本数')
    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('晋级质量')
    expect(wrapper.text()).toContain('需要精确相邻交易日和规范证券身份')
    expect(wrapper.text()).toContain('缺少收盘状态')
  })

  it('renders the latest attempt in the Shanghai market timezone', async () => {
    const limits = dataset('limits')
    limits.latestAttempt = { ...limits.latestAttempt!, completedAt: '2026-09-15T00:00:00Z' }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      datasets: allDatasets({ limits }),
    }) })))
    wrapper = mount(DataCollectionView)
    await flushPromises()

    const attemptTime = wrapper.find('[data-label="最近尝试"] time')
    expect(attemptTime.exists()).toBe(true)
    expect(attemptTime.text()).toBe('2026-09-15 08:00:00 GMT+8')
    const limitsRow = wrapper.findAll('tbody > tr').find((row) => row.text().includes('limits'))
    expect(limitsRow?.find('[data-label="最近成功"] span').text()).toBe('2026-09-10 16:00:00 GMT+8')
  })

  it('renders three independent THS daily datasets, blocked dependency and retry', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/market-environment/data-collection') {
        return { ok: true, json: async () => statusResponse({
          datasets: allDatasets({
            'industry-ranking': dataset('industry-ranking', undefined, { status: 'ok', catalogRevision: 'catalog-r7', coverage: 1 }),
            'sector-turnover': dataset('sector-turnover', undefined, { status: 'partial', sourceRevision: 'turnover-r3', coverage: 0.75 }),
            'sector-breadth': dataset('sector-breadth', undefined, { status: 'insufficient', dependency: 'sector-turnover' }, 'blocked'),
          }),
        }) }
      }
      if (url === '/api/market-environment/collection-runs' && init?.method === 'POST') {
        return { ok: true, json: async () => ({
          runId: 'run-retry', asOf: '2026-09-15', status: 'failed', requestedDatasets: ['sector-breadth'],
          completedTasks: 1, totalTasks: 1, createdAt: '', startedAt: '', completedAt: '', tasks: [],
        }) }
      }
      if (url === '/api/market-environment/collection-runs/run-retry') {
        return { ok: true, json: async () => ({
          runId: 'run-retry', asOf: '2026-09-15', status: 'failed', requestedDatasets: ['sector-breadth'],
          completedTasks: 1, totalTasks: 1, createdAt: '', startedAt: '', completedAt: '', tasks: [],
        }) }
      }
      return { ok: true, json: async () => statusResponse() }
    })
    vi.stubGlobal('fetch', fetchMock)
    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.text()).toContain('THS 分类排名')
    expect(wrapper.text()).toContain('THS 板块量价')
    expect(wrapper.text()).toContain('THS 板块宽度')
    expect(wrapper.text()).toContain('依赖阻塞')
    expect(wrapper.text()).toContain('正常 · 版本 catalog-r7 · 覆盖 100%')
    expect(wrapper.text()).toContain('部分覆盖 · 版本 turnover-r3 · 覆盖 75%')
    expect(wrapper.text()).toContain('依赖 sector-turnover')

    const breadthRow = wrapper.findAll('tbody > tr').find((row) => row.text().includes('sector-breadth'))
    expect(breadthRow).toBeTruthy()
    await breadthRow!.find('button.retry-button').trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find((call) => call[0] === '/api/market-environment/collection-runs')
    expect(JSON.parse((post?.[1] as RequestInit).body as string)).toEqual({ asOf: '2026-09-15', datasets: ['sector-breadth'] })
  })

  it('renders typed partial, failed and blocked THS diagnostics while retaining legacy warnings', async () => {
    const ranking = dataset(
      'industry-ranking',
      undefined,
      { status: 'partial', catalogRevisionId: 'catalog-r8' },
      'partial',
    )
    Object.assign(ranking.latestAttempt!, {
      warning: '部分代码缺少当日行情',
      diagnostics: {
        reasonCode: 'THS_LIVE_VALUES_MISSING', message: '部分代码缺少当日行情',
        failureStage: 'snapshot-value-classification', exactDate: '2026-09-15', retryable: true,
        catalogRevisionId: 'catalog-r8', expectedCount: 846, rankableCount: 844,
        missingLiveCount: 2, missingLiveCodes: ['883422.TI', '883999.TI'],
        missingRankingCount: 3,
        missingRankingCodes: ['883422.TI', '884001.TI', '884002.TI'],
      },
    })
    const turnover = dataset('sector-turnover', undefined, null, 'failed-missing')
    Object.assign(turnover.latestAttempt!, {
      warning: '每日快照身份校验失败',
      diagnostics: {
        reasonCode: 'THS_DAILY_SNAPSHOT_INSUFFICIENT', message: '每日快照身份校验失败',
        failureStage: 'snapshot-identity-validation', exactDate: '2026-09-15', retryable: true,
        expectedCount: 846, observedCount: 845,
      },
    })
    const breadth = dataset('sector-breadth', undefined, null, 'blocked')
    Object.assign(breadth.latestAttempt!, {
      warning: '上游数据不足',
      diagnostics: {
        reasonCode: 'THS_DEPENDENCY_INSUFFICIENT', message: '上游数据不足',
        failureStage: 'dependency-validation', exactDate: '2026-09-15', retryable: true,
        blockedBy: [{ dataset: 'industry-ranking', status: 'insufficient' }],
      },
    })
    const limits = dataset('limits')
    limits.latestAttempt!.warning = '旧版纯文本 warning 保持可读'
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      datasets: allDatasets({
        'industry-ranking': ranking,
        'sector-turnover': turnover,
        'sector-breadth': breadth,
        limits,
      }),
    }) })))

    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.text()).toContain('原因 THS_LIVE_VALUES_MISSING')
    expect(wrapper.text()).toContain('可用 844 / 预期 846')
    expect(wrapper.text()).toContain('当日行情缺失 2 个：883422.TI、883999.TI')
    expect(wrapper.text()).toContain('不可排名 3 个：883422.TI、884001.TI、884002.TI')
    expect(wrapper.text()).toContain('原因 THS_DAILY_SNAPSHOT_INSUFFICIENT')
    expect(wrapper.text()).toContain('原因 THS_DEPENDENCY_INSUFFICIENT')
    expect(wrapper.text()).toContain('上游：industry-ranking（insufficient）')
    expect(wrapper.text()).toContain('旧版纯文本 warning 保持可读')
  })

  it('renders safe structured messages for retained, missing, blocked and busy attempts while keeping partial warnings', async () => {
    const retained = dataset('limits', undefined, null, 'failed-retained')
    const missing = dataset('breadth', undefined, null, 'failed-missing')
    const blocked = dataset('sector-breadth', undefined, null, 'blocked')
    const busy = dataset('activeDirection', undefined, null, 'busy')
    const partial = dataset('industry-ranking', undefined, null, 'partial')
    const attempts = [
      [retained, 'network', '结构化保留原因', true],
      [missing, 'contract', '结构化缺失原因', false],
      [blocked, 'dependency', '结构化阻塞原因', false],
      [busy, 'concurrency', '结构化忙碌原因', false],
    ] as const
    for (const [item, category, message, retainedValue] of attempts) {
      Object.assign(item.latestAttempt!, {
        warning: `不应优先展示的 ${category} warning`,
        failure: { category, message, retryable: true, retained: retainedValue },
      })
    }
    partial.latestAttempt!.warning = '部分结果兼容提示'
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      datasets: allDatasets({
        limits: retained,
        breadth: missing,
        'sector-breadth': blocked,
        activeDirection: busy,
        'industry-ranking': partial,
      }),
    }) })))

    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.text()).toContain('失败，保留旧值')
    expect(wrapper.text()).toContain('失败，暂无数据')
    expect(wrapper.text()).toContain('依赖阻塞')
    expect(wrapper.text()).toContain('已有任务运行')
    expect(wrapper.text()).toContain('部分成功')
    for (const message of ['结构化保留原因', '结构化缺失原因', '结构化阻塞原因', '结构化忙碌原因', '部分结果兼容提示']) {
      expect(wrapper.text()).toContain(message)
    }
    expect(wrapper.text()).not.toContain('不应优先展示的 network warning')
  })

  it('shows explicit THS operation progress separately from daily tasks', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      operations: [{
        runId: 'ths-backfill-1', kind: 'turnover-backfill', status: 'partial',
        progress: { completed: 8, total: 10, failed: 1, conflicts: 2 },
        warning: '一个编号等待重试', checkpoints: [],
      }],
    }) })))
    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.text()).toContain('THS 目录、历史与成员事实进度')
    expect(wrapper.text()).toContain('turnover-backfill')
    expect(wrapper.text()).toContain('8 / 10')
    expect(wrapper.text()).toContain('失败 1')
    expect(wrapper.text()).toContain('冲突 2')
    expect(wrapper.text()).toContain('一个编号等待重试')
  })

  it('labels locally derived active direction and keeps continuity readiness read-only', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      sectorAnalysis: {
        asOf: '2026-09-15', status: 'partial', requiredHistory: 272, availableHistory: 180,
        missingSessions: ['2026-01-02', '2026-01-03'], coverage: 180 / 272,
        versions: { calculation: 'sector-continuity-v1' },
        latestAttempt: { status: 'failed-retained', retryEligible: true, warning: '部分日期待重试' },
        backfill: { runId: 'run-sector', status: 'partial', completedSessions: 180, totalSessions: 272, failedSessions: 2 },
        warnings: ['历史成员覆盖不足'], retryEligible: true,
      },
    }) })))
    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.text()).toContain('tdx-daily-package-derived')
    expect(wrapper.text()).toContain('本地派生降级 · 本地成交额排序 · 行业映射 50%')
    expect(wrapper.text()).toContain('Sector continuity readiness')
    expect(wrapper.text()).toContain('180 / 272')
    expect(wrapper.text()).toContain('2026-01-02')
    expect(wrapper.text()).toContain('只读状态')
    expect(wrapper.text()).toContain('不属于七个每日数据集')
    expect(wrapper.findAll('button').filter((button) => button.text().includes('回填')).length).toBe(0)
  })

  it('keeps the 390px layout structurally responsive without a page-level wide table', async () => {
    const ranking = dataset('industry-ranking', undefined, { status: 'partial' }, 'partial')
    Object.assign(ranking.latestAttempt!, {
      failure: null,
      diagnostics: {
        reasonCode: 'THS_LIVE_VALUES_MISSING', message: '部分代码缺少当日行情',
        failureStage: 'snapshot-value-classification', exactDate: '2026-09-15', retryable: true,
        expectedCount: 846, rankableCount: 844, missingLiveCount: 2,
        missingLiveCodes: ['883422.TI', '883999.TI'],
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse({
      datasets: allDatasets({ 'industry-ranking': ranking }),
    }) })))
    window.innerWidth = 390
    window.dispatchEvent(new Event('resize'))
    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.find('.collection-page').exists()).toBe(true)
    expect(wrapper.find('.collection-table-wrap').exists()).toBe(true)
    expect(wrapper.findAll('.sector-dataset-row')).toHaveLength(3)
    expect(wrapper.find('.ths-diagnostic-details').exists()).toBe(true)
    const page = wrapper.find('.collection-page').element as HTMLElement
    if (page.clientWidth > 0) expect(page.scrollWidth).toBeLessThanOrEqual(page.clientWidth)
    for (const node of wrapper.findAll('span, strong, button, th, td').filter((item) => item.isVisible())) {
      const fontSize = Number.parseFloat(getComputedStyle(node.element).fontSize)
      if (Number.isFinite(fontSize) && fontSize > 0) expect(fontSize).toBeGreaterThanOrEqual(14)
    }
  })
})
