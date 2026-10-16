/**
 * Market store — the reactive cache for the core `/api/market-environment`
 * payload plus its lazily-loaded chapter sections and the next-session
 * comparison. Owns all dashboard fetches; UI components subscribe via
 * `useMarketStore()` instead of holding local `ref`s.
 *
 * Lifecycle state machines
 * -------------------------
 * `loadCore()` bumps a private `coreSequence` counter; concurrent calls
 * whose responses arrive after a newer request is fired are dropped.
 * `loadSection()` keeps a separate `sectionSequences[section]` counter so
 * that two sections requested in parallel don't clobber each other, and a
 * `sectionEpoch` so a `loadCore()` that supersedes an in-flight section
 * request will drop that section's response.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  Chapter01Analysis,
  Chapter01Section,
  Chapter01SectionResponse,
  MarketEnvironmentResponse,
  NextSessionComparison,
} from '../types'
import { getDefaultMarketDate } from '../date-util'
import {
  fetchAllV2Pages,
  fetchV2CollectionWithOverviewRestart,
  fetchV2Overview,
  requestV2,
  V2ApiError,
  V2RevisionConflictError,
  type V2Envelope,
  type V2PaginatedEnvelope,
  type V2Quality,
} from '../market-v2-api'

type SectionState = { phase: 'idle' | 'loading' | 'ready' | 'refreshing' | 'error'; error: string }

const CHAPTER_SECTIONS = ['breadth', 'limits', 'sectors', 'activeDirection', 'summary'] as const
export type DashboardV2Resource =
  | 'indices'
  | 'breadth'
  | 'limits'
  | 'sector-rankings'
  | 'sector-turnover'
  | 'sector-breadth'
  | 'sector-analysis'
  | 'active-direction'
  | 'events'
  | 'assessment'

type V2ResourceState = { phase: SectionState['phase']; error: string }
type LimitPoolType = 'limit_up' | 'limit_down' | 'failed_limit_up' | 'promoted'

const V2_RESOURCES: DashboardV2Resource[] = [
  'indices', 'breadth', 'limits', 'sector-rankings', 'sector-turnover',
  'sector-breadth', 'sector-analysis', 'active-direction', 'events', 'assessment',
]

function createV2ResourceStates(): Record<DashboardV2Resource, V2ResourceState> {
  return Object.fromEntries(V2_RESOURCES.map((resource) => [resource, { phase: 'idle', error: '' }])) as Record<DashboardV2Resource, V2ResourceState>
}

function legacyQuality(quality: V2Quality, dataset: string) {
  return {
    ...quality,
    dataset,
    asOf: quality.actualDate ?? null,
    warning: quality.warnings?.[0] ?? null,
  }
}

function emptyAssessment() {
  return { state: 'insufficient', confidence: 'insufficient', evidence: [], risks: [], nextConfirmation: null, invalidation: null }
}

function emptyCombinationOverview() {
  return { strength: '数据不足', stage: '数据不足', capitalAcceptance: '数据不足', tradingMode: '数据不足', confidence: 'insufficient', evidence: [] }
}

function responseFromOverview(envelope: V2Envelope<Record<string, any>>): MarketEnvironmentResponse {
  const value = envelope.data ?? {}
  const summary = value.summary ?? { synchronization: '数据不足', dominantTrend: '数据不足', warnings: envelope.quality.warnings ?? [] }
  return {
    asOf: envelope.asOf,
    generatedAt: envelope.generatedAt,
    indices: [],
    summary: {
      synchronization: summary.synchronization ?? '数据不足',
      dominantTrend: summary.dominantTrend ?? '数据不足',
      warnings: summary.warnings ?? envelope.quality.warnings ?? [],
      ...summary,
    },
    chapter01: {
      status: value.status ?? envelope.quality.status,
      coverage: value.coverage ?? 0,
      combinationOverview: value.combinationOverview ?? emptyCombinationOverview(),
      assessment: value.assessment ?? emptyAssessment(),
      summarySentence: value.summarySentence ?? null,
      marketEvidence: value.marketEvidence ?? null,
      reviewSentence: value.reviewSentence ?? null,
      dataGaps: value.dataGaps ?? [],
    },
  } as MarketEnvironmentResponse
}

function createSectionStates(): Record<Chapter01Section, SectionState> {
  return Object.fromEntries(
    CHAPTER_SECTIONS.map((section) => [section, { phase: 'idle', error: '' }]),
  ) as Record<Chapter01Section, SectionState>
}

function hasSectorEvidence(chapter: Chapter01Analysis): boolean {
  return [
    chapter.industryRanking?.quality.status,
    chapter.sectorTurnover?.quality.status,
    chapter.sectorBreadth?.quality.status,
    chapter.sectorAnalysis?.quality.status,
  ].some((status) => status != null && status !== 'missing')
}

function mergeChapterSection(
  current: Chapter01Analysis | undefined,
  incoming: Chapter01Analysis,
  section: Chapter01Section,
): Chapter01Analysis {
  if (section === 'summary') return { ...incoming }
  const merged: Chapter01Analysis = current ? { ...current } : { ...incoming }
  merged.status = incoming.status
  merged.coverage = incoming.coverage
  if (incoming.documents) merged.documents = incoming.documents
  if (section === 'breadth' || incoming.breadth?.quality.status !== 'missing') merged.breadth = incoming.breadth
  if (section === 'limits' || incoming.limits?.quality.status !== 'missing') merged.limits = incoming.limits
  if (section === 'sectors' || hasSectorEvidence(incoming)) {
    merged.industryRanking = incoming.industryRanking
    merged.sectorTurnover = incoming.sectorTurnover
    merged.sectorBreadth = incoming.sectorBreadth
    merged.sectorAnalysis = incoming.sectorAnalysis
  }
  if (section === 'activeDirection' || incoming.activeDirection?.quality.status !== 'missing') {
    merged.activeDirection = incoming.activeDirection
  }
  merged.combinationOverview = incoming.combinationOverview
  merged.assessment = incoming.assessment
  return merged
}

function completedChapterSections(chapter: Chapter01Analysis, requested: Chapter01Section): Chapter01Section[] {
  const completed: Chapter01Section[] = [requested]
  if (chapter.breadth?.quality.status !== 'missing') completed.push('breadth')
  if (chapter.limits?.quality.status !== 'missing') completed.push('limits')
  if (hasSectorEvidence(chapter)) completed.push('sectors')
  if (chapter.activeDirection?.quality.status !== 'missing') completed.push('activeDirection')
  if (requested === 'summary') completed.push('summary')
  return completed
}

function retainLoadedChapterEvidence(
  previous: MarketEnvironmentResponse | null,
  incoming: MarketEnvironmentResponse,
  loaded: Chapter01Section[],
): MarketEnvironmentResponse {
  if (!previous?.chapter01 || previous.asOf !== incoming.asOf || loaded.length === 0) return incoming
  if (!incoming.chapter01) return { ...incoming, chapter01: { ...previous.chapter01 } }

  const retained = { ...incoming.chapter01 }
  if (loaded.includes('summary')) {
    retained.status = previous.chapter01.status
    retained.coverage = previous.chapter01.coverage
    retained.documents = previous.chapter01.documents
    retained.combinationOverview = previous.chapter01.combinationOverview
    retained.marketEvidence = previous.chapter01.marketEvidence
    retained.reviewSentence = previous.chapter01.reviewSentence
    retained.summarySentence = previous.chapter01.summarySentence
    retained.dataGaps = previous.chapter01.dataGaps
    retained.assessment = previous.chapter01.assessment
  }
  if (loaded.includes('breadth')) retained.breadth = previous.chapter01.breadth
  if (loaded.includes('limits')) retained.limits = previous.chapter01.limits
  if (loaded.includes('sectors')) {
    retained.industryRanking = previous.chapter01.industryRanking
    retained.sectorTurnover = previous.chapter01.sectorTurnover
    retained.sectorBreadth = previous.chapter01.sectorBreadth
    retained.sectorAnalysis = previous.chapter01.sectorAnalysis
  }
  if (loaded.includes('activeDirection')) retained.activeDirection = previous.chapter01.activeDirection
  return { ...incoming, chapter01: retained }
}

export const useMarketStore = defineStore('market', () => {
  // ── inputs ────────────────────────────────────────────────────────
  const selectedDate = ref(getDefaultMarketDate(new Date()))
  const selectedCode = ref('sh000001')
  const selectedDocumentId = ref('01')

  // ── core payload ──────────────────────────────────────────────────
  const data = ref<MarketEnvironmentResponse | null>(null)
  const loading = ref(false)
  const error = ref('')

  // ── additive v2 dashboard reads ─────────────────────────────────
  const v2Enabled = ref<boolean | null>(null)
  const v2Overview = ref<V2Envelope<Record<string, any>> | null>(null)
  const snapshotRevision = ref('')
  const v2ResourceStates = ref<Record<DashboardV2Resource, V2ResourceState>>(createV2ResourceStates())
  const loadedV2Resources = ref<DashboardV2Resource[]>([])
  const v2LimitPool = ref({
    poolType: 'limit_up' as LimitPoolType,
    rows: [] as Array<Record<string, any>>,
    quality: null as ReturnType<typeof legacyQuality> | null,
    hasMore: false,
    page: 1,
    loading: false,
    error: '',
  })
  const limitPoolCursors: Record<LimitPoolType, Array<string | null>> = {
    limit_up: [null], limit_down: [null], failed_limit_up: [null], promoted: [null],
  }

  // ── chapter sections ( lazy ──────────────────────────────────────
  const loadedSections = ref<Chapter01Section[]>([])
  const sectionStates = ref<Record<Chapter01Section, SectionState>>(createSectionStates())

  // ── next-session comparison ───────────────────────────────────────
  const nextSessionComparison = ref<NextSessionComparison | null>(null)

  // ── lifecycle bookkeeping (non-reactive, store-scoped) ──────────
  let coreSequence = 0
  let sectionEpoch = 0
  const sectionSequences: Record<Chapter01Section, number> = Object.fromEntries(
    CHAPTER_SECTIONS.map((section) => [section, 0]),
  ) as Record<Chapter01Section, number>
  let nextSessionSequence = 0
  let coreRequestedDate = ''

  function markV2Ready(resource: DashboardV2Resource): void {
    if (!loadedV2Resources.value.includes(resource)) loadedV2Resources.value = [...loadedV2Resources.value, resource]
    v2ResourceStates.value = { ...v2ResourceStates.value, [resource]: { phase: 'ready', error: '' } }
  }

  function mergeChapter(patch: Partial<Chapter01Analysis>): void {
    if (!data.value) return
    const current = data.value.chapter01 ?? ({
      status: 'insufficient', coverage: 0,
      combinationOverview: emptyCombinationOverview(), assessment: emptyAssessment(),
    } as Chapter01Analysis)
    data.value = { ...data.value, chapter01: { ...current, ...patch } }
  }

  async function readPinned<T>(path: string): Promise<V2Envelope<T>> {
    const read = async () => {
      const result = await requestV2<V2Envelope<T>>(path, { snapshotRevision: snapshotRevision.value })
      if (result.status === 'not-modified') throw new Error('资源读取收到意外的 304 响应')
      return result.envelope
    }
    try {
      return await read()
    } catch (cause) {
      if (!(cause instanceof V2RevisionConflictError)) throw cause
      const overviewResult = await fetchV2Overview<Record<string, any>>(selectedDate.value)
      if (overviewResult.status === 'not-modified') throw cause
      v2Overview.value = overviewResult.envelope
      snapshotRevision.value = overviewResult.envelope.snapshotRevision
      data.value = responseFromOverview(overviewResult.envelope)
      return read()
    }
  }

  function v2Root(): string {
    return `/api/v2/market-environment/${encodeURIComponent(selectedDate.value)}`
  }

  async function loadDashboardShell(force = false): Promise<void> {
    if (data.value && !force) return
    loading.value = true
    error.value = ''
    try {
      const result = await fetchV2Overview<Record<string, any>>(selectedDate.value)
      if (result.status === 'not-modified') throw new Error('overview 首次读取不能返回 304')
      v2Enabled.value = true
      v2Overview.value = result.envelope
      snapshotRevision.value = result.envelope.snapshotRevision
      data.value = responseFromOverview(result.envelope)
      if (force) {
        loadedV2Resources.value = []
        v2ResourceStates.value = createV2ResourceStates()
        loadedSections.value = []
      }
      coreRequestedDate = result.envelope.asOf
      if (result.envelope.asOf !== selectedDate.value) selectedDate.value = result.envelope.asOf
      void loadNextSession(result.envelope.asOf)
    } catch (cause) {
      if (cause instanceof V2ApiError && cause.code === 'snapshot_integrity_error') {
        v2Enabled.value = true
        v2Overview.value = null
        snapshotRevision.value = ''
        data.value = null
        error.value = cause.message || '本地市场数据完整性校验失败，请联系运维处理'
        return
      }
      v2Enabled.value = false
      await loadCore()
    } finally {
      loading.value = false
    }
  }

  async function loadSelectedIndexHistory(): Promise<void> {
    if (!v2Enabled.value || !data.value || !selectedCode.value || !snapshotRevision.value) return
    const path = `${v2Root()}/indices/${encodeURIComponent(selectedCode.value)}/history?limit=250`
    const result = await fetchV2CollectionWithOverviewRestart<Record<string, any>, Record<string, any>>({
      asOf: selectedDate.value,
      path,
      snapshotRevision: snapshotRevision.value,
      identity: (item) => String(item.date ?? item.asOf),
    })
    if (result.restarted && result.overview) {
      v2Overview.value = result.overview
      snapshotRevision.value = result.snapshotRevision
    }
    const index = data.value.indices.find((item) => item.code === selectedCode.value)
    if (!index) return
    data.value = {
      ...data.value,
      indices: data.value.indices.map((item) => item.code === selectedCode.value
        ? { ...item, history: result.items }
        : item),
    }
  }

  async function loadV2Resource(resource: DashboardV2Resource, force = false): Promise<void> {
    if (!v2Enabled.value || !data.value) return
    if (!force && loadedV2Resources.value.includes(resource)) return
    const previous = v2ResourceStates.value[resource]
    v2ResourceStates.value = {
      ...v2ResourceStates.value,
      [resource]: { phase: previous.phase === 'ready' ? 'refreshing' : 'loading', error: '' },
    }
    try {
      const root = v2Root()
      if (resource === 'indices') {
        const envelope = await readPinned<{ items: Array<Record<string, any>> }>(`${root}/indices`)
        const indices = (envelope.data.items ?? []).map((item) => ({ ...item, history: [] }))
        data.value = { ...data.value, generatedAt: envelope.generatedAt, indices: indices as never }
        if (!indices.some((item) => item.code === selectedCode.value)) selectedCode.value = String(indices[0]?.code ?? '')
        markV2Ready(resource)
        loadedSections.value = [...new Set([...loadedSections.value, 'summary'])]
        await loadSelectedIndexHistory()
        return
      }
      if (resource === 'breadth') {
        const envelope = await readPinned<Record<string, any>>(`${root}/breadth`)
        const pages = await fetchV2CollectionWithOverviewRestart<Record<string, any>, Record<string, any>>({
          asOf: selectedDate.value,
          path: `${root}/breadth/history?limit=250`,
          snapshotRevision: snapshotRevision.value,
          identity: (item) => String(item.asOf ?? item.date),
        })
        const breadth = {
          ...envelope.data,
          quality: legacyQuality(envelope.quality, 'market-breadth'),
          history: {
            points: pages.items,
            validObservations: pages.items.length,
            requiredObservations: pages.items.length,
            windowDays: pages.items.length,
            coverage: pages.items.length ? 1 : null,
            percentile250: {},
            quality: null,
          },
        }
        mergeChapter({ breadth: breadth as never })
        loadedSections.value = [...new Set([...loadedSections.value, 'breadth'])]
        markV2Ready(resource)
        return
      }
      if (resource === 'limits') {
        const [summary, evidence] = await Promise.all([
          readPinned<Record<string, any>>(`${root}/limits`),
          readPinned<Record<string, any>>(`${root}/limits/evidence`),
        ])
        mergeChapter({ limits: {
          ...summary.data,
          ...evidence.data,
          quality: legacyQuality(summary.quality, 'market-limits'),
          securityDetails: undefined,
        } as never })
        loadedSections.value = [...new Set([...loadedSections.value, 'limits'])]
        markV2Ready(resource)
        return
      }
      if (resource === 'sector-analysis' || resource === 'assessment') {
        const path = resource === 'sector-analysis' ? 'sectors/analysis' : 'assessment'
        const envelope = await readPinned<Record<string, any>>(`${root}/${path}`)
        if (resource === 'assessment') {
          mergeChapter({ assessment: envelope.data as never })
          loadedSections.value = [...new Set([...loadedSections.value, 'summary'])]
        } else mergeChapter({ sectorAnalysis: envelope.data as never })
        markV2Ready(resource)
        return
      }
      const pagePath: Record<Exclude<DashboardV2Resource, 'indices' | 'breadth' | 'limits' | 'sector-analysis' | 'assessment'>, string> = {
        'sector-rankings': 'sectors/rankings?limit=100',
        'sector-turnover': 'sectors/turnover?limit=100',
        'sector-breadth': 'sectors/breadth?limit=100',
        'active-direction': 'active-direction?limit=100',
        events: 'events?limit=100',
      }
      const result = await fetchV2CollectionWithOverviewRestart<Record<string, any>, Record<string, any>>({
        asOf: selectedDate.value,
        path: `${root}/${pagePath[resource as keyof typeof pagePath]}`,
        snapshotRevision: snapshotRevision.value,
        identity: (item) => String(item.securityId ?? item.thscode ?? item.code ?? item.id ?? `${item.title}:${item.publishedAt}`),
      })
      if (result.restarted && result.overview) {
        v2Overview.value = result.overview
        snapshotRevision.value = result.snapshotRevision
      }
      const quality = legacyQuality((result.quality ?? result.overview?.quality ?? v2Overview.value?.quality) as V2Quality, resource)
      if (resource === 'sector-rankings') mergeChapter({ industryRanking: { state: quality.status, asOf: data.value.asOf, rows: result.items, quality } as never })
      if (resource === 'sector-turnover') mergeChapter({ sectorTurnover: { state: quality.status, asOf: data.value.asOf, rows: result.items, quality } as never })
      if (resource === 'sector-breadth') mergeChapter({ sectorBreadth: { state: quality.status, asOf: data.value.asOf, rows: result.items, quality } as never })
      if (resource === 'active-direction') {
        mergeChapter({ activeDirection: { state: quality.status, topStocks: result.items, quality } as never })
        loadedSections.value = [...new Set([...loadedSections.value, 'activeDirection'])]
      }
      if (resource === 'events') mergeChapter({ events: { state: quality.status, items: result.items, quality } as never })
      if (resource.startsWith('sector-')) loadedSections.value = [...new Set([...loadedSections.value, 'sectors'])]
      markV2Ready(resource)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'v2 资源加载失败'
      v2ResourceStates.value = { ...v2ResourceStates.value, [resource]: { phase: 'error', error: message } }
      // A failed v2 resource falls back to the existing cumulative read path.
      v2Enabled.value = false
      await loadCore()
      const fallbackSection: Partial<Record<DashboardV2Resource, Chapter01Section>> = {
        breadth: 'breadth', limits: 'limits', 'sector-rankings': 'sectors',
        'sector-turnover': 'sectors', 'sector-breadth': 'sectors', 'sector-analysis': 'sectors',
        'active-direction': 'activeDirection', indices: 'summary', assessment: 'summary',
      }
      const section = fallbackSection[resource]
      if (section) await loadSection(section)
    }
  }

  async function loadV2LimitPool(poolType: LimitPoolType, direction: 'reset' | 'next' | 'previous' = 'reset'): Promise<void> {
    if (!v2Enabled.value || !snapshotRevision.value) return
    if (direction === 'reset' || v2LimitPool.value.poolType !== poolType) limitPoolCursors[poolType] = [null]
    let pageIndex = direction === 'reset' || v2LimitPool.value.poolType !== poolType ? 0 : v2LimitPool.value.page - 1
    if (direction === 'next') pageIndex += 1
    if (direction === 'previous') pageIndex = Math.max(0, pageIndex - 1)
    const cursor = limitPoolCursors[poolType][pageIndex] ?? null
    const base = `${v2Root()}/limits/pools/${poolType}?limit=20`
    const path = cursor ? `${base}&cursor=${encodeURIComponent(cursor)}` : base
    v2LimitPool.value = { ...v2LimitPool.value, poolType, loading: true, error: '' }
    try {
      const result = await requestV2<V2PaginatedEnvelope<{ items: Array<Record<string, any>> }>>(path, { snapshotRevision: snapshotRevision.value })
      if (result.status === 'not-modified') throw new Error('证券池读取收到意外的 304 响应')
      const envelope = result.envelope
      if (envelope.pagination.nextCursor) limitPoolCursors[poolType][pageIndex + 1] = envelope.pagination.nextCursor
      v2LimitPool.value = {
        poolType,
        rows: envelope.data.items ?? [],
        quality: legacyQuality(envelope.quality, `limits-${poolType}`),
        hasMore: envelope.pagination.hasMore,
        page: pageIndex + 1,
        loading: false,
        error: '',
      }
    } catch (cause) {
      v2LimitPool.value = { ...v2LimitPool.value, loading: false, error: cause instanceof Error ? cause.message : '证券池读取失败' }
    }
  }

  // ── actions ────────────────────────────────────────────────────────
  async function loadCore(): Promise<void> {
    const requestId = ++coreSequence
    const requestedDate = selectedDate.value
    const previousData = data.value
    const previousLoadedSections = [...loadedSections.value]
    const sameDateRefresh = previousData?.asOf === requestedDate
    ++sectionEpoch
    if (!sameDateRefresh) {
      data.value = null
      loadedSections.value = []
      sectionStates.value = createSectionStates()
      nextSessionComparison.value = null
      nextSessionSequence += 1
      coreRequestedDate = ''
    } else {
      const retainedStates = createSectionStates()
      for (const section of previousLoadedSections) retainedStates[section] = { phase: 'ready', error: '' }
      sectionStates.value = retainedStates
    }
    loading.value = true
    error.value = ''
    try {
      const response = await fetch(`/api/market-environment/core?as_of=${requestedDate}`)
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail || `请求失败（${response.status}）`)
      }
      const nextData = await response.json() as MarketEnvironmentResponse
      if (requestId !== coreSequence) return
      data.value = retainLoadedChapterEvidence(previousData, nextData, previousLoadedSections)
      void loadNextSession(nextData.asOf)
      // The API may resolve a weekend/holiday request to the latest valid
      // trading date. Keep both the date picker and lazy section requests on
      // that effective date so a later section cannot use the rejected input.
      const normalizeDate = nextData.asOf !== requestedDate
      if (normalizeDate) selectedDate.value = nextData.asOf
      coreRequestedDate = nextData.asOf
      if (!data.value.indices.some((item) => item.code === selectedCode.value)) {
 selectedCode.value = data.value.indices[0]?.code ?? ''
      }
    } catch (cause) {
      if (requestId !== coreSequence) return
      error.value = cause instanceof Error ? cause.message : '行情加载失败，请稍后重试'
    } finally {
      if (requestId !== coreSequence) return
      loading.value = false
    }
  }

  async function loadSection(section: Chapter01Section, force = false): Promise<void> {
    const requestedDate = coreRequestedDate
    if (!requestedDate || loading.value || !data.value || selectedDate.value !== requestedDate) return
    if (!force && loadedSections.value.includes(section)) {
      if (sectionStates.value[section].phase === 'idle') {
 sectionStates.value = { ...sectionStates.value, [section]: { phase: 'ready', error: '' } }
      }
      return
    }
    const epoch = sectionEpoch
    const requestId = ++sectionSequences[section]
    const hasEvidence = loadedSections.value.includes(section)
    sectionStates.value = {
      ...sectionStates.value,
      [section]: { phase: hasEvidence ? 'refreshing' : 'loading', error: '' },
    }
    try {
      const response = await fetch(
        `/api/market-environment/chapter-01?as_of=${requestedDate}&section=${section}`,
      )
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail || `请求失败（${response.status}）`)
      }
      const nextData = await response.json() as Chapter01SectionResponse
      if (
        epoch !== sectionEpoch
        || requestId !== sectionSequences[section]
        || requestedDate !== coreRequestedDate
        || !data.value
      ) return
      if (nextData.asOf !== data.value.asOf) throw new Error('章节数据日期与核心数据不一致')
      data.value = {
        ...data.value,
        generatedAt: nextData.generatedAt,
        summary: nextData.summary
          ? {
              ...data.value.summary,
              ...nextData.summary,
              synchronizationAssessment:
 nextData.summary.synchronizationAssessment
                ?? data.value.summary.synchronizationAssessment,
            }
          : data.value.summary,
        chapter01: mergeChapterSection(data.value.chapter01, nextData.chapter01, section),
      }
      const completed = completedChapterSections(nextData.chapter01, section)
      loadedSections.value = [...new Set([...loadedSections.value, ...completed])]
      sectionStates.value = { ...sectionStates.value, [section]: { phase: 'ready', error: '' } }
    } catch (cause) {
      if (
        epoch !== sectionEpoch
        || requestId !== sectionSequences[section]
        || requestedDate !== coreRequestedDate
      ) return
      sectionStates.value = {
        ...sectionStates.value,
        [section]: {
 phase: 'error',
          error: cause instanceof Error ? cause.message : '章节证据加载失败，请稍后重试',
        },
      }
    }
  }

  async function loadNextSession(asOf: string): Promise<void> {
    const requestId = ++nextSessionSequence
    try {
      const response = await fetch(`/api/market-environment/next-session?as_of=${asOf}`)
      if (!response.ok) return
      const value = await response.json() as NextSessionComparison
      if (requestId === nextSessionSequence) nextSessionComparison.value = value
    } catch {
      if (requestId === nextSessionSequence) nextSessionComparison.value = null
    }
  }

  function setDate(date: string): void {
    selectedDate.value = date
    if (v2Enabled.value === true) {
      data.value = null
      v2Overview.value = null
      snapshotRevision.value = ''
      loadedV2Resources.value = []
      v2ResourceStates.value = createV2ResourceStates()
      loadedSections.value = []
      void loadDashboardShell()
    } else void loadCore()
  }

  function setSelectedCode(code: string): void {
    selectedCode.value = code
    if (v2Enabled.value === true) void loadSelectedIndexHistory()
  }

  function setSelectedDocumentId(id: string): void {
    selectedDocumentId.value = id
  }

  function reset(): void {
    selectedDate.value = getDefaultMarketDate(new Date())
    selectedCode.value = 'sh000001'
    selectedDocumentId.value = '01'
    data.value = null
    loading.value = false
    error.value = ''
    v2Enabled.value = null
    v2Overview.value = null
    snapshotRevision.value = ''
    loadedV2Resources.value = []
    v2ResourceStates.value = createV2ResourceStates()
    v2LimitPool.value = {
      poolType: 'limit_up', rows: [], quality: null, hasMore: false,
      page: 1, loading: false, error: '',
    }
    loadedSections.value = []
    sectionStates.value = createSectionStates()
    nextSessionComparison.value = null
    coreSequence += 1
    sectionEpoch += 1
    nextSessionSequence += 1
    coreRequestedDate = ''
  }

  // ── derived getters ────────────────────────────────────────────────
  const selectedIndex = computed(() => {
    const indices = data.value?.indices ?? []
    return indices.find((item) => item.code === selectedCode.value) ?? indices[0] ?? null
  })
  const chapter = computed(() => data.value?.chapter01)
  const breadth = computed(() => chapter.value?.breadth)
  const limits = computed(() => chapter.value?.limits)
  const assessment = computed(() => chapter.value?.assessment)
  const combinationOverview = computed(() => chapter.value?.combinationOverview)
  const synchronizationAssessment = computed(() => data.value?.summary.synchronizationAssessment ?? null)
  const reviewSentence = computed(() => chapter.value?.reviewSentence ?? data.value?.summary.reviewSentence ?? null)

  return {
    // inputs
    selectedDate,
    selectedCode,
    selectedDocumentId,
    // core
    data,
    loading,
    error,
    v2Enabled,
    v2Overview,
    snapshotRevision,
    loadedV2Resources,
    v2ResourceStates,
    v2LimitPool,
    // sections
    loadedSections,
    sectionStates,
    // next session
    nextSessionComparison,
    // actions
    loadCore,
    loadDashboardShell,
    loadV2Resource,
    loadV2LimitPool,
    loadSection,
    loadNextSession,
    setDate,
    setSelectedCode,
    setSelectedDocumentId,
    reset,
    // getters
    selectedIndex,
    chapter,
    breadth,
    limits,
    assessment,
    combinationOverview,
    synchronizationAssessment,
    reviewSentence,
  }
})
