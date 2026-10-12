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
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => statusResponse() })))
    window.innerWidth = 390
    window.dispatchEvent(new Event('resize'))
    wrapper = mount(DataCollectionView)
    await flushPromises()

    expect(wrapper.find('.collection-page').exists()).toBe(true)
    expect(wrapper.find('.collection-table-wrap').exists()).toBe(true)
    expect(wrapper.findAll('.sector-dataset-row')).toHaveLength(3)
    for (const node of wrapper.findAll('span, strong, button, th, td').filter((item) => item.isVisible())) {
      const fontSize = Number.parseFloat(getComputedStyle(node.element).fontSize)
      if (Number.isFinite(fontSize) && fontSize > 0) expect(fontSize).toBeGreaterThanOrEqual(14)
    }
  })
})
