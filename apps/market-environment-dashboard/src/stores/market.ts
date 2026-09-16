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

type SectionState = { phase: 'idle' | 'loading' | 'ready' | 'refreshing' | 'error'; error: string }

const CHAPTER_SECTIONS = ['breadth', 'limits', 'sectors', 'activeDirection', 'summary'] as const

function createSectionStates(): Record<Chapter01Section, SectionState> {
  return Object.fromEntries(
    CHAPTER_SECTIONS.map((section) => [section, { phase: 'idle', error: '' }]),
  ) as Record<Chapter01Section, SectionState>
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
  if (section === 'sectors' || incoming.sectors?.quality.status !== 'missing') merged.sectors = incoming.sectors
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
  if (chapter.sectors?.quality.status !== 'missing') completed.push('sectors')
  if (chapter.activeDirection?.quality.status !== 'missing') completed.push('activeDirection')
  if (requested === 'summary') completed.push('summary')
  return completed
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
  let initialDatePending = true

  // ── actions ────────────────────────────────────────────────────────
  async function loadCore(): Promise<void> {
    const requestId = ++coreSequence
    const requestedDate = selectedDate.value
    ++sectionEpoch
    loadedSections.value = []
    sectionStates.value = createSectionStates()
    coreRequestedDate = ''
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
      data.value = nextData
      void loadNextSession(nextData.asOf)
      const normalizeInitialDate = initialDatePending && nextData.asOf !== requestedDate
      if (normalizeInitialDate) selectedDate.value = nextData.asOf
      coreRequestedDate = normalizeInitialDate ? nextData.asOf : requestedDate
      initialDatePending = false
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
    initialDatePending = false
    selectedDate.value = date
    void loadCore()
  }

  function setSelectedCode(code: string): void {
    selectedCode.value = code
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
    loadedSections.value = []
    sectionStates.value = createSectionStates()
    nextSessionComparison.value = null
    coreSequence += 1
    sectionEpoch += 1
    nextSessionSequence += 1
    coreRequestedDate = ''
    initialDatePending = true
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
    // sections
    loadedSections,
    sectionStates,
    // next session
    nextSessionComparison,
    // actions
    loadCore,
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