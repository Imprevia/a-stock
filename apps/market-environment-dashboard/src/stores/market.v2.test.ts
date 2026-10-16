import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketStore } from './market'

const AS_OF = '2026-08-28'
const ROOT = `/api/v2/market-environment/${AS_OF}`

function envelope(data: unknown, quality = { status: 'ok', actualDate: AS_OF, warnings: [] }) {
  return {
    asOf: AS_OF,
    generatedAt: `${AS_OF}T16:00:00+08:00`,
    snapshotRevision: 'sr1_fixture',
    quality,
    data,
    links: [],
  }
}

function page(items: unknown[], nextCursor: string | null = null) {
  return {
    ...envelope({ items }),
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
    expect(market.limits?.limitUpCount).toBe(50)
    expect(market.limits?.ruleEvidence).toEqual([{ ruleId: 'r1' }])
    expect(requests.some((url) => url.includes('/limits/pools/'))).toBe(false)
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
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
