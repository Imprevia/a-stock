import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchAllV2Pages,
  fetchV2CollectionWithOverviewRestart,
  requestV2,
  V2NotFoundError,
  V2RevisionConflictError,
  type V2Envelope,
  type V2PaginatedEnvelope,
} from './market-v2-api'

const AS_OF = '2026-08-28'
const OVERVIEW_PATH = `/api/v2/market-environment/${AS_OF}/overview`
const HISTORY_PATH = `/api/v2/market-environment/${AS_OF}/breadth/history?limit=2`

function quality() {
  return { status: 'ok' as const, warnings: [] }
}

function overview(revision: string): V2Envelope<{ resources: [] }> {
  return {
    asOf: AS_OF,
    generatedAt: `${AS_OF}T16:00:00+08:00`,
    snapshotRevision: revision,
    quality: quality(),
    data: { resources: [] },
    links: [],
  }
}

function page(
  revision: string,
  items: Array<{ id: string }>,
  nextCursor: string | null,
): V2PaginatedEnvelope<{ items: Array<{ id: string }> }> {
  return {
    asOf: AS_OF,
    generatedAt: `${AS_OF}T16:00:00+08:00`,
    snapshotRevision: revision,
    quality: quality(),
    data: { items },
    links: [],
    pagination: {
      limit: 2,
      returned: items.length,
      hasMore: nextCursor != null,
      nextCursor,
    },
  }
}

function jsonResponse(status: number, body: unknown, etag?: string): Response {
  return new Response(status === 304 ? null : JSON.stringify(body), {
    status,
    headers: {
      ...(status === 304 ? {} : { 'Content-Type': 'application/json' }),
      ...(etag ? { ETag: `"${etag}"` } : {}),
    },
  })
}

describe('market v2 API client', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns an explicit not-modified result for 304', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(304, null, 'sr1_current'))
    vi.stubGlobal('fetch', fetchMock)

    const result = await requestV2(OVERVIEW_PATH, { ifNoneMatch: 'sr1_current' })

    expect(result).toEqual({ status: 'not-modified', snapshotRevision: 'sr1_current' })
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('If-None-Match')).toBe('"sr1_current"')
  })

  it('throws a typed not-found error with the server error contract', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(404, {
      error: { code: 'market_date_not_found', message: '所选日期没有本地证据', parameter: 'as_of' },
    })))

    const request = requestV2(OVERVIEW_PATH)

    await expect(request).rejects.toBeInstanceOf(V2NotFoundError)
    await expect(request).rejects.toMatchObject({
      status: 404,
      code: 'market_date_not_found',
      parameter: 'as_of',
      message: '所选日期没有本地证据',
    })
  })

  it('continues cursor pages under one revision and keeps each identity once', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, page('sr1_current', [{ id: 'a' }, { id: 'b' }], 'cursor-2')))
      .mockResolvedValueOnce(jsonResponse(200, page('sr1_current', [{ id: 'b' }, { id: 'c' }], null)))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchAllV2Pages<{ id: string }>(
      HISTORY_PATH,
      'sr1_current',
      (item) => item.id,
    )

    expect(result).toMatchObject({
      items: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
      snapshotRevision: 'sr1_current',
      pageCount: 2,
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toBe(HISTORY_PATH)
    expect(fetchMock.mock.calls[1][0]).toBe(`${HISTORY_PATH}&cursor=cursor-2`)
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init.headers).get('If-Match')).toBe('"sr1_current"')
    }
  })

  it('refreshes overview and restarts the whole collection once after a 409', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(409, {
        error: {
          code: 'snapshot_revision_conflict',
          message: 'revision changed',
          requestedSnapshotRevision: 'sr1_old',
          currentSnapshotRevision: 'sr1_new',
        },
      }, 'sr1_new'))
      .mockResolvedValueOnce(jsonResponse(200, overview('sr1_new'), 'sr1_new'))
      .mockResolvedValueOnce(jsonResponse(200, page('sr1_new', [{ id: 'a' }], 'cursor-new-2')))
      .mockResolvedValueOnce(jsonResponse(200, page('sr1_new', [{ id: 'b' }], null)))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchV2CollectionWithOverviewRestart<{ id: string }, { resources: [] }>({
      asOf: AS_OF,
      path: HISTORY_PATH,
      snapshotRevision: 'sr1_old',
      identity: (item) => item.id,
    })

    expect(result.restarted).toBe(true)
    expect(result.snapshotRevision).toBe('sr1_new')
    expect(result.items).toEqual([{ id: 'a' }, { id: 'b' }])
    expect(result.overview?.snapshotRevision).toBe('sr1_new')
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      HISTORY_PATH,
      OVERVIEW_PATH,
      HISTORY_PATH,
      `${HISTORY_PATH}&cursor=cursor-new-2`,
    ])
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('If-Match')).toBe('"sr1_old"')
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get('If-Match')).toBeNull()
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('If-Match')).toBe('"sr1_new"')
  })

  it('does not hide a second revision conflict after the single restart', async () => {
    const conflict = (requested: string, current: string) => jsonResponse(409, {
      error: {
        code: 'snapshot_revision_conflict',
        message: 'revision changed again',
        requestedSnapshotRevision: requested,
        currentSnapshotRevision: current,
      },
    })
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(conflict('sr1_old', 'sr1_new'))
      .mockResolvedValueOnce(jsonResponse(200, overview('sr1_new')))
      .mockResolvedValueOnce(conflict('sr1_new', 'sr1_newer')))

    await expect(fetchV2CollectionWithOverviewRestart({
      asOf: AS_OF,
      path: HISTORY_PATH,
      snapshotRevision: 'sr1_old',
      identity: (item: { id: string }) => item.id,
    })).rejects.toBeInstanceOf(V2RevisionConflictError)
  })
})
