// @vitest-environment happy-dom

import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketStore } from './market'

function indexItem(position: number) {
  return {
    code: `index-${position}`,
    name: `指数${position}`,
    representative: 'fixture',
    changePct: position / 10,
    close: 100 + position,
    movingAverages: { ma5: 102, ma10: 101, ma20: 100, ma60: 99 },
    rangePosition20: 0.6,
    rangePosition60: 0.5,
    rangePosition20Label: '偏强区域',
    rangePosition60Label: '区间中部',
    amount: 1000,
    amountRatio5: 1.1,
    amountRatio20: 1,
    trendState: '偏强',
    volumePriceState: '量价平稳',
    combination: {
      key: 'rotation',
      state: '震荡轮动',
      matched: true,
      tone: 'neutral',
      evidence: [`指数${position} evidence`],
      tradingMode: '轮动应对',
    },
    history: [],
    dataQuality: { source: 'fixture', isStale: false, warning: null },
    dataGaps: [],
  }
}

function coreResponse(asOf = '2026-09-03') {
  return {
    asOf,
    generatedAt: `${asOf}T16:00:00+08:00`,
    indices: Array.from({ length: 5 }, (_, index) => indexItem(index)),
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
  }
}

function sectionResponse(asOf = '2026-09-03') {
  return {
    asOf,
    generatedAt: `${asOf}T16:00:00+08:00`,
    summary: { synchronization: 'fixture', dominantTrend: 'fixture', warnings: [] },
    chapter01: {
      status: 'ok',
      coverage: 0.8,
      combinationOverview: { strength: 'fixture', stage: 'fixture', capitalAcceptance: 'fixture', tradingMode: 'fixture', confidence: 'fixture', evidence: [] },
      assessment: { state: 'fixture', confidence: 'fixture', evidence: [], risks: [], nextConfirmation: '', invalidation: '' },
    },
  }
}

describe('market store — loadCore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('populates data from /core and normalises initial date to response.asOf', async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => coreResponse('2026-09-03'),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = useMarketStore()
    store.selectedDate = '2026-09-01' // initialDatePending path
    await store.loadCore()

    expect(store.data?.asOf).toBe('2026-09-03')
    expect(store.selectedDate).toBe('2026-09-03')
    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
  })

  it('records the API error message when /core returns non-OK', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'fixture 503' }),
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = useMarketStore()
    await store.loadCore()

    expect(store.data).toBeNull()
    expect(store.error).toBe('fixture 503')
    expect(store.loading).toBe(false)
  })

  it('drops the response when a newer loadCore supersedes it', async () => {
    let resolveFirst!: (value: unknown) => void
    let resolveSecond!: (value: unknown) => void
    const firstResponse = new Promise((resolve) => { resolveFirst = resolve })
    const secondResponse = new Promise((resolve) => { resolveSecond = resolve })
    let call = 0
    const fetchMock = vi.fn(async () => {
      call += 1
      const payload = call === 1 ? firstResponse : secondResponse
      return { ok: true, json: async () => payload }
    }) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = useMarketStore()
    const first = store.loadCore()
    const second = store.loadCore()
    // Resolve the second one first; the first's resolve should be discarded.
    resolveSecond(coreResponse('2026-09-04'))
    resolveFirst(coreResponse('2026-09-03'))
    await Promise.all([first, second])

    expect(store.data?.asOf).toBe('2026-09-04')
  })
})

describe('market store — loadSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('does nothing when no core has loaded yet (coreRequestedDate is empty)', async () => {
    const fetchMock = vi.fn() as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const store = useMarketStore()
    await store.loadSection('limits')

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('skips the request when the section is already loaded', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => coreResponse() })) as unknown as typeof fetch)
    const store = useMarketStore()
    await store.loadCore()

    const fetchMock = vi.fn() as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)
    // Pre-mark the section as already loaded; the second call should NOT
    // hit the API because `force` defaults to false.
    store.loadedSections = ['limits']
    store.sectionStates = { ...store.sectionStates, limits: { phase: 'ready', error: '' } }

    await store.loadSection('limits')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('merges the section payload into data.chapter01 and records the section state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => coreResponse() })) as unknown as typeof fetch)
    const store = useMarketStore()
    await store.loadCore()

    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => sectionResponse('2026-09-03'),
    })) as unknown as typeof fetch)
    await store.loadSection('breadth')

    expect(store.loadedSections).toContain('breadth')
    expect(store.sectionStates.breadth.phase).toBe('ready')
    expect(store.data?.chapter01?.coverage).toBe(0.8)
  })
})

describe('market store — setDate / setSelectedCode', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => coreResponse() })) as unknown as typeof fetch)
  })

  it('setDate triggers loadCore and clears initialDatePending', async () => {
    const store = useMarketStore()
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => coreResponse() })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    await store.setDate('2026-09-05')

    expect(store.selectedDate).toBe('2026-09-05')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('setSelectedCode updates the selected index lookup', () => {
    const store = useMarketStore()
    store.data = coreResponse() as unknown as Parameters<typeof store.loadCore>[0] & typeof store.data
    store.setSelectedCode('index-2')
    expect(store.selectedIndex?.code).toBe('index-2')
  })
})

describe('market store — reset', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => coreResponse() })) as unknown as typeof fetch)
  })

  it('clears data, sections, and next-session comparison', async () => {
    const store = useMarketStore()
    await store.loadCore()
    store.reset()

    expect(store.data).toBeNull()
    expect(store.loadedSections).toEqual([])
    expect(store.nextSessionComparison).toBeNull()
    expect(store.selectedDate).not.toBe('')
  })
})