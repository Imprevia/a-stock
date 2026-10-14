import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  COLLECTION_DATASETS,
  LEGACY_SECTORS_MIGRATION_MESSAGE,
  fetchThsCatalog,
  fetchThsOperation,
  fetchThsSectorBars,
  fetchCollectionStatus,
  pollCollectionRun,
  pollThsOperation,
  startSectorTurnoverBackfill,
  startCollectionRun,
  startThsCatalogSync,
  startThsMemberFactsImport,
} from './collection-api'
import type {
  CollectionRun,
  DatasetCollectionStatus,
} from './collection-api'
import {
  attemptLabel,
  availabilityLabel,
  canCollectAll,
  canRetryDataset,
  collectionDiagnosticDetails,
  getCollectionStatusRequestDate,
  resolveCollectionSelectedDate,
  statusTone,
  toggleCoreExpansion,
} from './collection-view-model'

const run: CollectionRun = {
  runId: 'run-1',
  asOf: '2026-09-03',
  status: 'collecting',
  requestedDatasets: ['breadth'],
  completedTasks: 0,
  totalTasks: 1,
  createdAt: '2026-09-03T15:20:00+08:00',
  startedAt: '2026-09-03T15:20:00+08:00',
  completedAt: null,
  tasks: [],
}

const dataset: DatasetCollectionStatus = {
  dataset: 'breadth',
  available: true,
  source: 'fixture',
  observations: 3,
  lastSuccessAt: '2026-09-03T15:20:00+08:00',
  settled: true,
  refreshWarning: null,
  latestAttempt: {
    taskId: 'task-1',
    runId: 'run-1',
    status: 'failed-retained',
    source: 'fixture',
    observations: 3,
    warning: 'provider unavailable',
    queuedAt: null,
    startedAt: null,
    completedAt: null,
    durationMs: 120,
    settled: true,
  },
  activeTaskId: null,
  collectionAllowed: true,
  restriction: null,
  coreIndices: [],
}

function jsonResponse(value: unknown) {
  return {
    ok: true,
    json: async () => value,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('collection view model', () => {
  it('maps retained failures without hiding available data', () => {
    expect(availabilityLabel(dataset)).toBe('可用 · 已结算')
    expect(attemptLabel(dataset)).toBe('失败，保留旧值')
    expect(statusTone(dataset.latestAttempt?.status)).toBe('warning')
  })

  it('controls row retry, full collection, disabled actions, and core expansion', () => {
    expect(canRetryDataset(true, dataset, null)).toBe(true)
    expect(canRetryDataset(false, dataset, null)).toBe(false)
    expect(canRetryDataset(true, { ...dataset, collectionAllowed: false }, null)).toBe(false)
    expect(canRetryDataset(true, dataset, run)).toBe(false)
    expect(canCollectAll(true, [dataset], null)).toBe(true)
    expect(canCollectAll(true, [dataset, { ...dataset, collectionAllowed: false }], null)).toBe(false)
    expect(toggleCoreExpansion(false)).toBe(true)
    expect(toggleCoreExpansion(true)).toBe(false)
  })

  it('uses the server date initially and preserves an explicit user date', () => {
    expect(getCollectionStatusRequestDate('', false)).toBeUndefined()
    expect(resolveCollectionSelectedDate('', false, '2026-09-03')).toBe('2026-09-03')
    expect(getCollectionStatusRequestDate('2026-09-02', true)).toBe('2026-09-02')
    expect(resolveCollectionSelectedDate('2026-09-02', true, '2026-09-03')).toBe('2026-09-02')
  })

  it('formats bounded THS coverage, missing identities and upstream details', () => {
    const ths = {
      ...dataset,
      dataset: 'sector-breadth' as const,
      latestAttempt: {
        ...dataset.latestAttempt!,
        status: 'blocked' as const,
        diagnostics: {
          reasonCode: 'THS_DEPENDENCY_INSUFFICIENT' as const,
          message: '上游可排名数据不足',
          failureStage: 'dependency-validation',
          exactDate: '2026-09-03',
          retryable: true,
          catalogRevisionId: 'catalog-r7',
          expectedCount: 846,
          usableCount: 844,
          missingLiveCount: 2,
          missingLiveCodes: ['883422.TI', '883999.TI'],
          blockedBy: [{ dataset: 'industry-ranking', status: 'insufficient' }],
        },
      },
    }

    expect(collectionDiagnosticDetails(ths)).toEqual([
      '原因 THS_DEPENDENCY_INSUFFICIENT',
      '可用 844 / 预期 846',
      '当日行情缺失 2 个：883422.TI、883999.TI',
      '上游：industry-ranking（insufficient）',
      '目录版本 catalog-r7',
      '阶段 dependency-validation',
      '可重试',
    ])
  })
})

describe('collection API', () => {
  it('exposes seven supported datasets and rejects legacy sectors before fetch', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    expect(COLLECTION_DATASETS).toEqual([
      'core', 'breadth', 'limits', 'industry-ranking', 'sector-turnover', 'sector-breadth', 'activeDirection',
    ])
    expect(COLLECTION_DATASETS).not.toContain('sectors')

    await expect(startCollectionRun('2026-09-03', ['sectors'] as never)).rejects.toThrow(LEGACY_SECTORS_MIGRATION_MESSAGE)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('omits as_of on first load and preserves explicit dates', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ asOf: '2026-09-03', datasets: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchCollectionStatus()
    await fetchCollectionStatus('2026-09-02')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/market-environment/data-collection')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/market-environment/data-collection?as_of=2026-09-02')
  })

  it('starts a targeted row retry and a full collection request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...run, status: 'queued' }))
    vi.stubGlobal('fetch', fetchMock)

    await startCollectionRun('2026-09-03', ['breadth'])
    await startCollectionRun('2026-09-03')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      asOf: '2026-09-03',
      datasets: ['breadth'],
    })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ asOf: '2026-09-03' })
  })

  it('polls until a partial run reaches a terminal result', async () => {
    const completed = { ...run, status: 'partial', completedTasks: 1 } as CollectionRun
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(run))
      .mockResolvedValueOnce(jsonResponse(completed))
    vi.stubGlobal('fetch', fetchMock)

    const result = await pollCollectionRun('run-1', { intervalMs: 1 })

    expect(result?.status).toBe('partial')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('drops a stale poll response after the selected request changes', async () => {
    let current = true
    const fetchMock = vi.fn().mockImplementation(async () => {
      current = false
      return jsonResponse(run)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await pollCollectionRun('run-1', { isCurrent: () => current })

    expect(result).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('uses provider-free THS catalog, bars, and operation query routes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchThsCatalog({ tag: 'cn_concept', search: 'AI', revision: 'catalog-r1', page: 2, pageSize: 30 })
    await fetchThsSectorBars('885001.TI', { startDate: '2025-01-01', endDate: '2026-09-03', page: 1, pageSize: 500 })
    await fetchThsOperation('run/1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/market-environment/ths/catalog?tag=cn_concept&search=AI&revision=catalog-r1&page=2&page_size=30')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/market-environment/ths/sectors/885001.TI/bars?start_date=2025-01-01&end_date=2026-09-03&page=1&page_size=500')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/market-environment/ths/operations/run%2F1')
  })

  it('normalizes a legacy catalog revisionId response to catalogRevisionId', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      revision: {
        revisionId: 'legacy-catalog-r1', capabilityRevision: 'cap-r1',
        providerTimestamp: '2026-09-03T16:00:00+08:00', fetchedAt: '2026-09-03T16:01:00+08:00',
        tagCounts: { industry: 1, cn_concept: 0, region: 0, tszs: 0 }, checksum: 'abc',
      },
      items: [], page: 1, pageSize: 100, total: 0,
    }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchThsCatalog()

    expect(response.revision?.catalogRevisionId).toBe('legacy-catalog-r1')
    expect(response.revision?.revisionId).toBe('legacy-catalog-r1')
  })

  it('submits and polls an explicit THS breadth membership selection', async () => {
    const queued = { runId: 'catalog-run', status: 'queued' }
    const completed = {
      runId: 'catalog-run', kind: 'catalog-sync', status: 'partial', warning: null,
      progress: { completed: 5, total: 6, failed: 1, conflicts: 0 }, checkpoints: [],
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(queued))
      .mockResolvedValueOnce(jsonResponse({ ...completed, status: 'running' }))
      .mockResolvedValueOnce(jsonResponse(completed))
    vi.stubGlobal('fetch', fetchMock)

    await startThsCatalogSync({
      asOf: '2026-09-03',
      membershipThscodes: ['885001.TI'],
    })
    const result = await pollThsOperation('catalog-run', { intervalMs: 1 })

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      asOf: '2026-09-03', membershipThscodes: ['885001.TI'],
    })
    expect(result?.status).toBe('partial')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/market-environment/ths/operations/catalog-run')
  })

  it('starts an explicit bounded turnover backfill with camelCase fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ runId: 'run-ths', status: 'queued' }))
    vi.stubGlobal('fetch', fetchMock)

    await startSectorTurnoverBackfill({
      thscodes: ['885001.TI'],
      startDate: '2025-01-01',
      endDate: '2026-09-03',
      requestBudget: 12,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/market-environment/ths/turnover/backfills')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      thscodes: ['885001.TI'], startDate: '2025-01-01', endDate: '2026-09-03', requestBudget: 12,
    })
  })

  it('sends the verified member dump manifests expected by the backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ runId: 'run-import', status: 'queued' }))
    vi.stubGlobal('fetch', fetchMock)
    const dump = {
      path: '/staging/daily.parquet',
      dumpId: 'daily-20260903',
      schemaRevision: 'daily-v1',
      capabilityRevision: 'daily-cap-v1',
      checksum: 'abc123',
      startDate: '2026-09-03',
      endDate: '2026-09-03',
    }

    await startThsMemberFactsImport({
      asOf: '2026-09-03',
      sourceRevision: 'member-facts-v1',
      daily: dump,
      adjustment: { ...dump, path: '/staging/adjustment.parquet', dumpId: 'adjustment-20260903' },
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/market-environment/ths/member-facts/imports')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      asOf: '2026-09-03',
      sourceRevision: 'member-facts-v1',
      daily: { dumpId: 'daily-20260903', schemaRevision: 'daily-v1' },
      adjustment: { dumpId: 'adjustment-20260903', schemaRevision: 'daily-v1' },
    })
  })
})
