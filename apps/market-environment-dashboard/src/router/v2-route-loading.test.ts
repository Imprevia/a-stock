import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useMarketStore } from '../stores/market'
import { registerRouterGuards } from './guards'
import { routes } from './routes'

const AS_OF = '2026-08-28'
const ROOT = `/api/v2/market-environment/${AS_OF}`

function envelope(data: unknown) {
  return {
    asOf: AS_OF,
    generatedAt: `${AS_OF}T16:00:00+08:00`,
    snapshotRevision: 'sr1_routes',
    quality: { status: 'ok', actualDate: AS_OF, warnings: [] },
    data,
    links: [],
  }
}

function page(items: unknown[]) {
  return { ...envelope({ items }), pagination: { limit: 100, returned: items.length, hasMore: false, nextCursor: null } }
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json', ETag: '"sr1_routes"' } })
}

function fetchForRoutes(requests: string[]) {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    requests.push(url)
    if (url === `${ROOT}/overview`) return json(envelope({ summary: { synchronization: '同步', dominantTrend: '震荡', warnings: [] }, status: 'ok', coverage: 1 }))
    if (url === '/api/market-environment/next-session?as_of=2026-08-28') return json({ status: 'insufficient', requestedAsOf: AS_OF, currentAsOf: null, nextAsOf: null, current: null, next: null, deltas: {}, warnings: [] })
    if (url === `${ROOT}/indices`) return json(envelope({ items: [{ code: '000001.SH', name: '上证指数', close: 1, changePct: 0, movingAverages: {}, combination: {}, dataQuality: {} }] }))
    if (url === `${ROOT}/indices/000001.SH/history?limit=250`) return json(page([]))
    if (url === `${ROOT}/breadth`) return json(envelope({ state: 'ok' }))
    if (url === `${ROOT}/breadth/history?limit=250`) return json(page([]))
    if (url === `${ROOT}/events?limit=100`) return json(page([{ id: 'e1', title: 'direct event' }]))
    if (url === `${ROOT}/assessment`) return json(envelope({ state: 'rotation', confidence: 'medium', evidence: [], risks: [] }))
    throw new Error(`unexpected request: ${url}`)
  })
}

async function navigate(path: string, requests: string[]) {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.selectedDate = AS_OF
  vi.stubGlobal('fetch', fetchForRoutes(requests))
  const router = createRouter({ history: createMemoryHistory(), routes })
  registerRouterGuards(router)
  await router.push(path)
  await router.isReady()
  return market
}

describe('v2 dashboard route loading', () => {
  beforeEach(() => vi.unstubAllGlobals())
  afterEach(() => vi.unstubAllGlobals())

  it('loads page 01 indices without breadth or cumulative chapter requests', async () => {
    const requests: string[] = []
    await navigate('/dashboard/01', requests)

    expect(requests).toContain(`${ROOT}/indices`)
    expect(requests).toContain(`${ROOT}/indices/000001.SH/history?limit=250`)
    expect(requests.some((url) => url.includes('/breadth'))).toBe(false)
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
  })

  it('loads page 02 breadth without index or cumulative chapter payloads', async () => {
    const requests: string[] = []
    await navigate('/dashboard/02', requests)

    expect(requests).toContain(`${ROOT}/breadth`)
    expect(requests).toContain(`${ROOT}/breadth/history?limit=250`)
    expect(requests.some((url) => url.includes('/indices'))).toBe(false)
    expect(requests.some((url) => url.includes('/chapter-01'))).toBe(false)
  })

  it('direct navigation to page 07 loads events independently', async () => {
    const requests: string[] = []
    const market = await navigate('/dashboard/07', requests)

    expect(market.chapter?.events?.items?.[0].title).toBe('direct event')
    expect(requests).toContain(`${ROOT}/events?limit=100`)
    expect(requests.some((url) => url.includes('/indices') || url.includes('/chapter-01'))).toBe(false)
  })

  it('direct navigation to page 09 loads assessment independently', async () => {
    const requests: string[] = []
    const market = await navigate('/dashboard/09', requests)

    expect(market.assessment?.state).toBe('rotation')
    expect(requests).toContain(`${ROOT}/assessment`)
    expect(requests.some((url) => url.includes('/indices') || url.includes('/chapter-01'))).toBe(false)
  })
})
