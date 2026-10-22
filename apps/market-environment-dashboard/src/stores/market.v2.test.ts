import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketStore } from './market'

const AS_OF = '2026-08-28'
const ROOT = `/api/v2/market-environment/${AS_OF}`

function envelope(
  data: unknown,
  quality = { status: 'ok', actualDate: AS_OF, warnings: [] },
  snapshotRevision = 'sr1_fixture',
) {
  return {
    asOf: AS_OF,
    generatedAt: `${AS_OF}T16:00:00+08:00`,
    snapshotRevision,
    quality,
    data,
    links: [],
  }
}

function page(items: unknown[], nextCursor: string | null = null, snapshotRevision = 'sr1_fixture') {
  return {
    ...envelope({ items }, { status: 'ok', actualDate: AS_OF, warnings: [] }, snapshotRevision),
    pagination: { limit: 100, returned: items.length, hasMore: nextCursor != null, nextCursor },
  }
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ETag: '"sr1_fixture"' },
  })
}

function fixtureFetch(requests: string[]) {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    requests.push(url)
    if (url === `${ROOT}/overview`) return response(envelope({
      summary: { synchronization: '同步', dominantTrend: '震荡', warnings: [] },
      status: 'partial', coverage: 0.75,
    }))
    if (url === '/api/market-environment/next-session?as_of=2026-08-28') return response({
      status: 'insufficient', requestedAsOf: AS_OF, currentAsOf: null, nextAsOf: null,
      current: null, next: null, deltas: {}, warnings: [],
    })
    if (url === `${ROOT}/indices`) return response(envelope({ items: [{
      code: '000001.SH', name: '上证指数', close: 3200, changePct: 0.5,
      movingAverages: { ma5: 1, ma10: 1, ma20: 1, ma60: 1 },
      rangePosition20: 0.5, rangePosition60: 0.5, rangePosition20Label: '中位', rangePosition60Label: '中位',
      amount: 1, amountRatio5: 1, amountRatio20: 1, trendState: '震荡', volumePriceState: null,
      combination: { key: 'rotation', state: '震荡', matched: true, tone: 'flat', evidence: [], tradingMode: '观察' },
      dataQuality: { source: 'local', isStale: false, warning: null },
    }] }))
    if (url === `${ROOT}/indices/000001.SH/history?limit=250`) return response(page([{ date: AS_OF, open: 1, high: 2, low: 1, close: 2, amount: 1 }]))
    if (url === `${ROOT}/breadth`) return response(envelope({ advanceCount: 3000, declineCount: 1500, state: 'ok' }))
    if (url === `${ROOT}/breadth/history?limit=250`) return response(page([{ asOf: AS_OF, advanceCount: 3000 }]))
    if (url === `${ROOT}/limits`) return response(envelope({ limitUpCount: 50, limitDownCount: 3, state: 'ok' }))
    if (url === `${ROOT}/limits/evidence`) return response(envelope({ ruleEvidence: [{ ruleId: 'r1' }], riskEvidence: [] }))
    if (url === `${ROOT}/limits/pools/limit_up?limit=20`) return response({ ...page([{ securityId: 'SH:1', code: '1' }], 'cursor-2'), pagination: { limit: 20, returned: 1, hasMore: true, nextCursor: 'cursor-2' } })
    if (url === `${ROOT}/limits/pools/limit_up?limit=20&cursor=cursor-2`) return response({ ...page([{ securityId: 'SH:2', code: '2' }]), pagination: { limit: 20, returned: 1, hasMore: false, nextCursor: null } })
    if (url === `${ROOT}/limits/pools/limit_down?limit=20`) return response({ ...page([{ securityId: 'SH:3', code: '3' }]), pagination: { limit: 20, returned: 1, hasMore: false, nextCursor: null } })
    if (url === `${ROOT}/sectors/rankings?limit=100`) return response(page([{ tag: 'industry', rank: 1, thscode: '885001.TI', name: '行业一', asOf: AS_OF }]))
    if (url === `${ROOT}/sectors/breadth?limit=100`) return response(page([{ thscode: '885001.TI', name: '行业一', asOf: AS_OF }]))
    if (url === `${ROOT}/sectors/turnover?limit=100`) return response(page([{ thscode: '885001.TI', tradingDate: AS_OF }]))
    if (url === `${ROOT}/sectors/analysis`) return response(envelope({ asOf: AS_OF, candidates: [] }))
    if (url === `${ROOT}/active-direction?limit=100`) return response(page([{ code: '000001', name: '活跃股' }]))
    if (url === `${ROOT}/events?limit=100`) return response(page([{ id: 'event-1', title: '事件一' }]))
    if (url === `${ROOT}/assessment`) return response(envelope({ state: 'rotation', confidence: 'medium', evidence: ['e1'], risks: [] }))
    throw new Error(`unexpected request: ${url}`)
  })
}

describe('market store v2 dashboard resources', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads overview and only the selected index history without a chapter request', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', fixtureFetch(requests))
    const market = useMarketStore()
    market.selectedDate = AS_OF

    await market.loadDashboardShell()
    await market.loadV2Resource('indices')

    expect(market.v2Enabled).toBe(true)
    expect(market.data?.indices[0].history).toHaveLength(1)
    expect(requests).toContain(`${ROOT}/overview`)
    expect(requests).toContain(`${ROOT}/indices`)
    expect(requests).toContain(`${ROOT}/indices/000001.SH/history?limit=250`)
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
  })

  it('surfaces snapshot integrity failure without falling back to legacy data', async () => {
    const fetchMock = vi.fn(async () => response({
      error: {
        code: 'snapshot_integrity_error',
        message: '本地市场数据完整性校验失败，请联系运维审计对应日期的数据。',
      },
    }, 503))
    vi.stubGlobal('fetch', fetchMock)
    const market = useMarketStore()
    market.selectedDate = AS_OF

    await market.loadDashboardShell()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe(`${ROOT}/overview`)
    expect(market.v2Enabled).toBe(true)
    expect(market.data).toBeNull()
    expect(market.error).toContain('完整性校验失败')
  })

  it('loads breadth and limits from isolated summary/history/evidence resources', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', fixtureFetch(requests))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('breadth')
    await market.loadV2Resource('limits')

    expect(market.breadth?.advanceCount).toBe(3000)
    expect(market.breadth?.history?.points).toHaveLength(1)
    expect(market.breadth?.history?.validObservations).toBe(1)
    expect(market.breadth?.history?.requiredObservations).toBe(60)
    expect(market.breadth?.history?.windowDays).toBe(250)
    expect(market.breadth?.history?.coverage).toBe(0.004)
    expect(market.breadth?.history?.quality?.status).toBe('insufficient')
    expect(market.limits?.limitUpCount).toBe(50)
    expect(market.limits?.ruleEvidence).toEqual([{ ruleId: 'r1' }])
    expect(requests.some((url) => url.includes('/limits/pools/'))).toBe(false)
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
  })

  it('keeps a successful breadth summary when history fails and retries history alone', async () => {
    let historyAttempts = 0
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      requests.push(url)
      if (url === `${ROOT}/overview`) return response(envelope({ summary: {}, status: 'partial', coverage: 0.5 }))
      if (url === '/api/market-environment/next-session?as_of=2026-08-28') return response({ status: 'insufficient' })
      if (url === `${ROOT}/breadth`) return response(envelope({
        advanceCount: 2273,
        declineCount: 3129,
        flatCount: 165,
        validCount: 5567,
        medianReturn: -0.3814,
        widthLabel: '同向走弱',
      }))
      if (url === `${ROOT}/breadth/history?limit=250`) {
        historyAttempts += 1
        if (historyAttempts === 1) return response({ error: { code: 'http_500', message: '历史服务暂不可用' } }, 500)
        return response(page([{ asOf: AS_OF, advanceCount: 2273, declineCount: 3129 }]))
      }
      throw new Error(`unexpected request: ${url}`)
    }))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('breadth')

    expect(market.breadth?.advanceCount).toBe(2273)
    expect(market.breadth?.declineCount).toBe(3129)
    expect(market.breadth?.medianReturn).toBe(-0.3814)
    expect(market.breadth?.widthLabel).toBe('同向走弱')
    expect(market.breadthHistoryState.phase).toBe('error')
    expect(market.v2ResourceStates.breadth.phase).toBe('ready')
    expect(market.v2Enabled).toBe(true)
    expect(requests.some((url) => url.includes('/api/market-environment/core') || url.includes('/chapter-01'))).toBe(false)

    await market.retryBreadthHistory()

    expect(market.breadthHistoryState.phase).toBe('ready')
    expect(market.breadth?.history?.points).toHaveLength(1)
    expect(requests.filter((url) => url === `${ROOT}/breadth`)).toHaveLength(1)
  })

  it.each([
    { count: 0, expectedPoints: 0, expectedStatus: 'insufficient', expectedCoverage: 0 },
    { count: 26, expectedPoints: 5, expectedStatus: 'insufficient', expectedCoverage: 26 / 250 },
    { count: 65, expectedPoints: 5, expectedStatus: 'ok', expectedCoverage: 65 / 250 },
  ])('normalizes $count unique history rows to the 60/250 contract', async ({ count, expectedPoints, expectedStatus, expectedCoverage }) => {
    const items = Array.from({ length: count }, (_, index) => {
      const value = new Date(Date.UTC(2026, 0, 1 + index))
      return { asOf: value.toISOString().slice(0, 10), advanceCount: index }
    })
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url === `${ROOT}/overview`) return response(envelope({ summary: {}, status: 'partial', coverage: 0.5 }))
      if (url === '/api/market-environment/next-session?as_of=2026-08-28') return response({ status: 'insufficient' })
      if (url === `${ROOT}/breadth`) return response(envelope({ advanceCount: 10, declineCount: 20, medianReturn: -0.1 }))
      if (url === `${ROOT}/breadth/history?limit=250`) return response(page(items))
      throw new Error(`unexpected request: ${url}`)
    }))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('breadth')

    expect(market.breadth?.history?.validObservations).toBe(count)
    expect(market.breadth?.history?.requiredObservations).toBe(60)
    expect(market.breadth?.history?.windowDays).toBe(250)
    expect(market.breadth?.history?.coverage).toBe(expectedCoverage)
    expect(market.breadth?.history?.quality?.status).toBe(expectedStatus)
    expect(market.breadth?.history?.points).toHaveLength(expectedPoints)
    if (count > 5) expect(market.breadth?.history?.points?.[0].advanceCount).toBe(count - 5)
  })

  it('restarts overview, summary, and history together after a history revision conflict', async () => {
    let overviewReads = 0
    let summaryReads = 0
    let historyReads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url === `${ROOT}/overview`) {
        overviewReads += 1
        const revision = overviewReads === 1 ? 'sr1_old' : 'sr1_new'
        return response(envelope({ summary: {}, status: 'partial', coverage: 0.5 }, undefined, revision))
      }
      if (url === '/api/market-environment/next-session?as_of=2026-08-28') return response({ status: 'insufficient' })
      if (url === `${ROOT}/breadth`) {
        summaryReads += 1
        const revision = summaryReads === 1 ? 'sr1_old' : 'sr1_new'
        return response(envelope({
          advanceCount: summaryReads === 1 ? 100 : 200,
          declineCount: summaryReads === 1 ? 300 : 250,
          medianReturn: summaryReads === 1 ? -1 : 0.5,
        }, undefined, revision))
      }
      if (url === `${ROOT}/breadth/history?limit=250`) {
        historyReads += 1
        if (historyReads === 1) return response({
          error: {
            code: 'snapshot_revision_conflict',
            message: 'revision changed',
            requestedSnapshotRevision: 'sr1_old',
            currentSnapshotRevision: 'sr1_new',
          },
        }, 409)
        return response(page([{ asOf: AS_OF, advanceCount: 200 }], null, 'sr1_new'))
      }
      throw new Error(`unexpected request: ${url}`)
    }))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('breadth')

    expect(overviewReads).toBe(2)
    expect(summaryReads).toBe(2)
    expect(historyReads).toBe(2)
    expect(market.snapshotRevision).toBe('sr1_new')
    expect(market.breadth?.advanceCount).toBe(200)
    expect(market.breadth?.medianReturn).toBe(0.5)
    expect(market.breadth?.history?.points?.[0].advanceCount).toBe(200)
  })

  it('fails closed when the breadth summary itself has an integrity error', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      requests.push(url)
      if (url === `${ROOT}/overview`) return response(envelope({ summary: {}, status: 'partial', coverage: 0.5 }))
      if (url === '/api/market-environment/next-session?as_of=2026-08-28') return response({ status: 'insufficient' })
      if (url === `${ROOT}/breadth`) return response({
        error: { code: 'snapshot_integrity_error', message: '市场广度完整性错误' },
      }, 503)
      throw new Error(`unexpected request: ${url}`)
    }))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('breadth')

    expect(market.breadth).toBeUndefined()
    expect(market.v2Enabled).toBe(true)
    expect(market.v2ResourceStates.breadth.phase).toBe('error')
    expect(requests.some((url) => url.includes('/api/market-environment/core') || url.includes('/chapter-01'))).toBe(false)
  })

  it('loads sector tabs independently and direct events/assessment resources', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', fixtureFetch(requests))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()

    await market.loadV2Resource('sector-rankings')
    expect(market.chapter?.industryRanking?.rows).toHaveLength(1)
    expect(requests).not.toContain(`${ROOT}/sectors/breadth?limit=100`)
    expect(requests).not.toContain(`${ROOT}/sectors/turnover?limit=100`)
    expect(requests).not.toContain(`${ROOT}/sectors/analysis`)

    await market.loadV2Resource('events')
    await market.loadV2Resource('assessment')
    expect(market.chapter?.events?.items?.[0].title).toBe('事件一')
    expect(market.assessment?.state).toBe('rotation')
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
  })

  it('loads only the active limits pool page and follows its server cursor', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', fixtureFetch(requests))
    const market = useMarketStore()
    market.selectedDate = AS_OF
    await market.loadDashboardShell()
    await market.loadV2Resource('limits')

    expect(requests.some((url) => url.includes('/limits/pools/'))).toBe(false)
    await market.loadV2LimitPool('limit_up', 'reset')
    expect(market.v2LimitPool.rows.map((row) => row.securityId)).toEqual(['SH:1'])
    expect(market.v2LimitPool.hasMore).toBe(true)
    await market.loadV2LimitPool('limit_up', 'next')
    expect(market.v2LimitPool.rows.map((row) => row.securityId)).toEqual(['SH:2'])
    expect(market.v2LimitPool.page).toBe(2)
    await market.loadV2LimitPool('limit_up', 'previous')
    expect(market.v2LimitPool.rows.map((row) => row.securityId)).toEqual(['SH:1'])
    await market.loadV2LimitPool('limit_down', 'reset')
    expect(market.v2LimitPool.rows.map((row) => row.securityId)).toEqual(['SH:3'])
    expect(requests.some((url) => url.includes('failed_limit_up') || url.includes('/promoted'))).toBe(false)
  })
})
