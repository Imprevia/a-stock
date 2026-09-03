import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchCollectionStatus,
  pollCollectionRun,
  startCollectionRun,
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
})

describe('collection API', () => {
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
})
