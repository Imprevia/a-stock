export interface HistoryPoint {
  date: string
  open: number
  close: number
  low: number
  high: number
  ma5: number | null
  ma10: number | null
  ma20: number | null
  ma60: number | null
  amount: number
}

export interface IndexCombination {
  key: string
  state: string | null
  matched: boolean
  tone: string
  evidence: string[]
  tradingMode: string
}

export type DataGapReason = 'insufficient-history' | 'missing-today' | 'provider-failed' | 'not-computable'

export interface DataGap {
  field: string
  reason: DataGapReason
}

export interface IndexAnalysis {
  code: string
  name: string
  representative: string
  changePct: number | null
  close: number
  movingAverages: {
    ma5: number | null
    ma10: number | null
    ma20: number | null
    ma60: number | null
  }
  rangePosition20: number | null
  rangePosition60: number | null
  rangePosition20Label: string
  rangePosition60Label: string
  amount: number
  amountRatio5: number | null
  amountRatio20: number | null
  ma20SlopePercentile?: number | null
  advanceEfficiencyPercentile?: number | null
  ma20SlopeConfidence?: string | null
  advanceEfficiencyConfidence?: string | null
  ma20PositionLabel?: string | null
  trendState: string
  volumePriceState: string | null
  combination: IndexCombination
  history: HistoryPoint[]
  dataQuality: {
    source: string
    isStale: boolean
    warning: string | null
  }
  dataGaps?: DataGap[]
}

export type SynchronizationAssessmentStatus = 'confirmed' | 'unconfirmed' | 'contradicted' | 'insufficient'
export type SynchronizationDimensionStatus = 'confirming' | 'neutral' | 'contradicting' | 'insufficient'
export type SynchronizationConfidence = 'high' | 'medium' | 'low' | 'insufficient'

export interface SynchronizationBreadthDimension {
  status: SynchronizationDimensionStatus
  currentAsOf: string | null
  previousAsOf: string | null
  advanceRatio: number | null
  medianReturn: number | null
  advanceRatioDelta: number | null
  medianReturnDelta: number | null
  comparisonStatus: 'available' | 'insufficient'
  reason: string | null
  comparisonReason: string | null
  evidence: string[]
}

export interface SynchronizationTrendDimension {
  status: SynchronizationDimensionStatus
  aboveMa20Count: number
  belowMa20Count: number
  validCount: number
  reason: string | null
  evidence: string[]
}

export interface SynchronizationTurnoverDimension {
  status: SynchronizationDimensionStatus
  medianAmountRatio5: number | null
  growthMedianAmountRatio5: number | null
  volumeBackedAdvanceCount: number
  volumeBackedDeclineCount: number
  validCount: number
  reason: string | null
  evidence: string[]
}

export interface SynchronizationAssessment {
  patternCode: string
  patternLabel: string
  status: SynchronizationAssessmentStatus
  conclusionCode: string
  conclusion: string
  confidence: SynchronizationConfidence
  allFiveWeak: boolean
  dimensions: {
    breadth: SynchronizationBreadthDimension
    trend: SynchronizationTrendDimension
    turnover: SynchronizationTurnoverDimension
  }
  evidence: string[]
  risks: string[]
}

export interface MarketSummary {
  synchronization: string
  syncPattern?: { code: string; label: string; score: number; evidence: string[] } | null
  synchronizationAssessment?: SynchronizationAssessment | null
  bullishAlignmentRatio?: number | null
  marketEvidence?: MarketReviewEvidence | null
  reviewSentence?: ReviewSentence | null
  dataGaps?: DataGap[]
  dominantTrend: string
  warnings: string[]
}

export interface MarketEnvironmentResponse {
  asOf: string
  generatedAt: string
  indices: IndexAnalysis[]
  summary: MarketSummary
  chapter01?: Chapter01Analysis
}

export type Chapter01Section = 'breadth' | 'limits' | 'sectors' | 'activeDirection' | 'summary'

export interface Chapter01SectionResponse {
  asOf: string
  generatedAt: string
  summary?: MarketSummary | null
  chapter01: Chapter01Analysis
}

export type ThsDiagnosticReasonCode =
  | 'THS_LIVE_VALUES_MISSING'
  | 'THS_DAILY_SNAPSHOT_INSUFFICIENT'
  | 'THS_CATALOG_REVISION_COLLISION'
  | 'THS_DEPENDENCY_INSUFFICIENT'
  | 'THS_DEPENDENCY_REVISION_MISMATCH'

export interface ThsBlockedByDiagnostic {
  dataset: string
  status: string
  reasonCode?: ThsDiagnosticReasonCode | null
  exactDate?: string | null
  catalogRevisionId?: string | null
}

export interface ThsDiagnostic {
  reasonCode: ThsDiagnosticReasonCode
  message: string
  failureStage: string
  exactDate: string
  retryable: boolean
  capabilityRevision?: string | null
  catalogRevisionId?: string | null
  expectedCount?: number | null
  observedCount?: number | null
  usableCount?: number | null
  rankableCount?: number | null
  barCount?: number | null
  missingLiveCount?: number | null
  missingLiveCodes?: string[]
  missingRankingCount?: number | null
  missingRankingCodes?: string[]
  existingChecksum?: string | null
  observedChecksum?: string | null
  blockedBy?: ThsBlockedByDiagnostic[]
}

export interface DataSetQuality {
  dataset?: string
  source: string
  provider?: string
  status: 'ok' | 'partial' | 'fallback' | 'missing' | 'failed' | 'degraded' | 'insufficient' | string
  warning?: string | null
  warnings?: string[]
  observations?: number | null
  asOf?: string | null
  cacheState?: 'fresh' | 'stale' | 'missing' | string | null
  snapshotFetchedAt?: string | null
  refreshing?: boolean | null
  refreshWarning?: string | null
  derived?: boolean
  rankingMethod?: string | null
  sourceRevision?: string | null
  catalogRevisionId?: string | null
  expectedCount?: number | null
  observedCount?: number | null
  usableCount?: number | null
  rankableCount?: number | null
  barCount?: number | null
  missingLiveCount?: number | null
  missingLiveCodes?: string[]
  missingRankingCount?: number | null
  missingRankingCodes?: string[]
  diagnostics?: ThsDiagnostic | null
  industryMappingRevision?: string | null
  industryMappingCoverage?: number | null
  industryMappingCovered?: number | null
  industryMappingTotal?: number | null
  sectorEnrichment?: SectorEnrichmentQuality | null
}

export interface SectorEnrichmentQuality {
  status?: string | null
  source?: string | null
  sameVendor?: boolean | null
  mappingRevision?: string | null
  matchedRows?: number | null
  unmatchedRows?: number | null
  identityCoverage?: number | null
  fieldCoverage?: Record<string, unknown> | null
  dateEvidence?: string | Record<string, unknown> | null
  warnings?: string[]
}

export type MetricQualityStatus = 'ok' | 'insufficient' | 'degraded' | 'failed' | string
export interface MetricQuality {
  status: MetricQualityStatus
  reason?: string | null
  observations?: number | null
  asOf?: string | null
  source?: string | null
  warnings?: string[]
}

export type LimitMetricField = 'todayPromoted' | 'yesterdayLimitUpEligible' | 'promotionRatio'

export interface LimitTierRow {
  tier: string
  label?: string | null
  count: number | null
  observations?: number | null
  quality?: MetricQuality | null
}

export interface LimitStratificationRow {
  dimension?: string
  key: string
  label?: string | null
  count: number | null
  observations?: number | null
  quality?: MetricQuality | null
}

export interface LimitHistoryPoint {
  asOf: string
  limitUpCount: number | null
  limitDownCount: number | null
  failedLimitUpRatio: number | null
  promotionRatio: number | null
  maxStreak: number | null
  quality?: MetricQuality | null
}

export interface LimitRuleEvidence {
  ruleId: string
  weight?: number | null
  status?: string | null
  score?: number | null
  confidence?: string | null
  evidence?: string[]
  missingInputs?: string[]
  calibrationStatus?: string | null
}

export interface LimitSecurityDetailRow {
  securityId: string
  thscode: string | null
  code: string
  exchange: string
  name: string | null
  poolType: 'limit_up' | 'limit_down' | 'failed_limit_up'
  isSt: boolean | null
  isNew: boolean | null
  listingDate: string | null
  closePrice: number | null
  changePct: number | null
  streakDays: number | null
  limitUpTime: string | null
  limitUpReason: string | null
  sealMoney: number | null
  maxSealMoney: number | null
  firstLimitTime: string | null
  lastLimitTime: string | null
  openTimes: number | null
  turnoverRatioPct: number | null
  turnover: number | null
  source: string
  rowQuality: string | null
  warnings: string[]
}

export interface LimitSecurityDetailGroup {
  total: number | null
  rows: LimitSecurityDetailRow[]
  quality: MetricQuality
}

export interface LimitSecurityDetails {
  limitUp: LimitSecurityDetailGroup
  limitDown: LimitSecurityDetailGroup
  failedLimitUp: LimitSecurityDetailGroup
  promoted: LimitSecurityDetailGroup
}

export interface ChapterDocument {
  id: string
  title: string
  document?: string
  status?: string
  ruleVersion?: string
}

export interface BreadthHistoryPoint {
  asOf: string
  advanceCount: number | null
  declineCount: number | null
  flatCount: number | null
  validCount: number | null
  advanceRatio: number | null
  declineRatio: number | null
  advanceDeclineSpread: number | null
  medianReturn: number | null
  momentum: number | null
  widthLabel: string | null
  indexConsistent: boolean | null
  quality: DataSetQuality
}

export interface BreadthHistoryEvidence {
  points: BreadthHistoryPoint[]
  validObservations: number
  requiredObservations: number
  windowDays: number
  coverage: number | null
  percentile250: Record<string, number | null>
  quality: MetricQuality | null
}

export interface BreadthAnalysis {
  advanceCount: number | null
  declineCount: number | null
  flatCount: number | null
  validCount: number | null
  advanceRatio: number | null
  medianReturn: number | null
  state: string
  quality: DataSetQuality
  declineRatio: number | null
  advanceDeclineSpread: number | null
  advanceRatioPercentile: number | null
  medianReturnPercentile: number | null
  spreadPercentile: number | null
  momentum: number | null
  momentumPercentile: number | null
  indexConsistent: boolean | null
  widthLabel: string | null
  widthLabelReason: string | null
  history: BreadthHistoryEvidence | null
}

export interface LimitAnalysis {
  limitUpCount: number | null
  limitDownCount: number | null
  failedLimitUpCount: number | null
  failedLimitUpRatio: number | null
  todayPromoted?: number | null
  yesterdayLimitUpEligible?: number | null
  promotionRatio?: number | null
  promotionSampleAsOf?: string | null
  promotionPreviousAsOf?: string | null
  promotionSampleRule?: string | null
  promotionRuleVersion?: string | null
  promotionQuality?: MetricQuality | null
  fieldQuality?: Partial<Record<LimitMetricField, MetricQuality>> | null
  membershipQuality?: MetricQuality | null
  streakQuality?: MetricQuality | null
  poolQuality?: Record<string, MetricQuality> | null
  maxStreak: number | null
  ladder?: LimitTierRow[] | null
  tiers?: LimitTierRow[] | null
  stratifications?: LimitStratificationRow[] | null
  history?: {
    points?: LimitHistoryPoint[] | null
    validObservations?: number | null
    requiredObservations?: number | null
    windowDays?: number | null
    coverage?: number | null
    percentile250?: Record<string, number | null> | null
    quality?: MetricQuality | null
  } | null
  historical?: {
    points?: LimitHistoryPoint[] | null
    validObservations?: number | null
    requiredObservations?: number | null
    windowDays?: number | null
    coverage?: number | null
    percentile250?: Record<string, number | null> | null
    quality?: MetricQuality | null
  } | null
  ruleEvidence?: Array<LimitRuleEvidence & { value?: number | string | null; thresholdProvenance?: string | null; vetoes?: string[] }> | null
  riskEvidence?: Array<{ code?: string; label: string; status?: string | null; value?: string | number | null; asOf?: string | null; evidence?: string[]; quality?: MetricQuality | null }> | null
  securityDetails?: LimitSecurityDetails | null
  confirmation?: string | null
  invalidation?: string | null
  state: string
  quality: DataSetQuality
}

export interface SectorRow {
  rank?: number
  code?: string | null
  name: string | null
  changePct?: number | null
  amount?: number | null
  upCount?: number | null
  downCount?: number | null
  leader?: string | null
  mainNet?: number | null
  mainNetPct?: number | null
}

export type ThsSectorTag = 'industry' | 'cn_concept' | 'region' | 'tszs'

export interface ThsIndustryRankingRow {
  tag: ThsSectorTag
  rank: number
  thscode: string
  name: string
  changePct: number | null
  volume: number | null
  turnover: number | null
  catalogRevisionId?: string | null
  catalogRevision?: string | null
  asOf: string
  quality?: string | null
  warnings?: string[]
}

export interface ThsIndustryRanking {
  state: string
  asOf?: string | null
  catalogRevisionId?: string | null
  revisionId?: string | null
  diagnostics?: ThsDiagnostic | null
  rows: ThsIndustryRankingRow[]
  quality: DataSetQuality
}

export interface ThsSectorBar {
  thscode?: string | null
  name?: string | null
  tradingDate: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  turnover: number | null
  quality: string
  source: string
  sourceRevision: string
  warnings: string[]
}

export interface ThsSectorTurnover {
  state: string
  asOf?: string | null
  rows: ThsSectorBar[]
  quality: DataSetQuality
}

export interface ThsMemberRanking {
  securityId: string
  name?: string | null
  value: number
}

export interface ThsSectorBreadthRow {
  thscode: string
  name?: string | null
  tag?: ThsSectorTag | null
  asOf: string
  selectionReasons: string[]
  memberCount: number
  validDirectionCount: number
  advanceCount: number
  declineCount: number
  flatCount: number
  advanceRatio: number | null
  advanceDeclineSpreadRatio: number | null
  medianChangePct: number | null
  validMa20Count: number
  closeAboveMa20Count: number
  ma20Breadth: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  topByTurnover: ThsMemberRanking[]
  topByGain: ThsMemberRanking[]
  maxMemberTurnoverContribution: number | null
  diffusionRate: number | null
  quality: string
  warnings: string[]
  lineage: Record<string, string>
}

export interface ThsSectorBreadth {
  state: string
  asOf?: string | null
  rows: ThsSectorBreadthRow[]
  quality: DataSetQuality
}

export type SectorContinuityStatus =
  | 'ok'
  | 'partial'
  | 'degraded'
  | 'reduced-confidence'
  | 'insufficient'
  | 'missing'
  | 'failed'
  | string

export type SectorCandidateStage =
  | 'insufficient'
  | 'high-level-crowding'
  | 'mainline-confirmed'
  | 'mainline-candidate'
  | 'one-day-pulse'
  | 'rotation-or-ebb'

export interface SectorAnalysisQuality {
  status: SectorContinuityStatus
  confidence: 'high' | 'medium' | 'low' | 'insufficient' | string
  coverage: number | null
  asOf: string
  requiredObservations: number
  availableObservations: number
  warnings: string[]
  missingInputs: string[]
}

export interface SectorAnalysisHistory {
  requiredObservations: number
  windowDays: number
  validObservations: number
  actualDateRange: string[]
  gaps: string[]
  quality?: MetricQuality | null
}

export interface SectorMetricTrace {
  ruleId: string
  value: number | null
  percentile: number | null
  score: number | null
  status: MetricQualityStatus
  weight: number
  originalWeight: number
  normalizedWeight: number | null
  observations: number
  requiredObservations: number
  windowDays: number
  missingReason: string | null
  sampleDates: string[]
  actualDateRange: string[]
  gaps: string[]
  raw: Record<string, unknown>
}

export interface SectorStructureSecurity {
  securityId?: string | null
  code?: string | null
  name?: string | null
  rank?: number | null
  amount?: number | null
  returnPct?: number | null
  contribution?: number | null
  [key: string]: unknown
}

export interface SectorInternalStructure {
  effectiveMemberCount: number
  advancingCount: number | null
  decliningCount: number | null
  flatCount: number | null
  limitUpCount: number | null
  limitDownCount: number | null
  topByTurnover: SectorStructureSecurity[]
  topByReturn: SectorStructureSecurity[]
  topSecurityTurnoverContribution: number | null
  diffusionRatio: number | null
}

export interface SectorCandidate {
  industryId: string
  displayName: string
  stage: SectorCandidateStage
  totalScore: number | null
  coreScores: Record<string, number | null>
  ruleTraces: SectorMetricTrace[]
  crowdingRisk: boolean | null
  vetoes: string[]
  internalStructure: SectorInternalStructure | null
  confirmationStreak: number
}

export interface SectorUniqueValidation {
  candidateIndustry: string | null
  candidateName: string | null
  stage: SectorCandidateStage
  persistenceEvidence: string
  breadthEvidence: string
  turnoverEvidence: string
  internalStructure: string
  target: string
  confirmationCondition: string
  invalidationCondition: string
}

export interface SectorAnalysisAttempt {
  runId: string | null
  status: 'success' | 'partial' | 'failed-retained' | 'failed-missing' | 'insufficient' | string
  retryEligible: boolean
  warning: string | null
  compatibleResultChecksum: string | null
}

export interface SectorContinuityRisk {
  status?: string | null
  crowdingRisk?: boolean | null
  concentrationPercentile?: number | null
  breadthPercentile?: number | null
  vetoes?: string[]
  warnings?: string[]
  [key: string]: unknown
}

export interface SectorContinuityAnalysis {
  asOf: string
  status: SectorContinuityStatus
  quality: SectorAnalysisQuality
  history: SectorAnalysisHistory | null
  metricTraces: SectorMetricTrace[]
  candidates: SectorCandidate[]
  validation: SectorUniqueValidation
  risk: SectorContinuityRisk
  lineage: Record<string, unknown>
  latestAttempt: SectorAnalysisAttempt | null
  warnings: string[]
}

export interface SectorObservation {
  state: string
  rows: SectorRow[]
  quality: DataSetQuality
  analysis?: SectorContinuityAnalysis | null
}

/** Backward-compatible name used by existing chapter consumers. */
export type SectorAnalysis = SectorObservation

export interface ActiveStock {
  code: string | null
  name: string | null
  changePct?: number | null
  amount?: number | null
  industry?: string | null
  closePosition?: number | null
}

export interface ActiveResearchRow extends ActiveStock {
  rank: number
  rawDirectionLabel?: string | null
  source?: string | null
  sourceRevision?: string | null
  industryMappingRevision?: string | null
  industryMappingCoverage?: number | null
  rowQuality?: string
  open?: number | null
  high?: number | null
  low?: number | null
  previousClose?: number | null
  turnoverRatePct?: number | null
  pe?: number | null
  pb?: number | null
  marketCap?: number | null
  circulatingMarketCap?: number | null
  changePct60d?: number | null
  changePctYtd?: number | null
  fundamentalAsOf?: string | null
  fundamentalSource?: string | null
}

export interface ActiveDirectionAnalysis {
  state: string
  summary?: string | null
  topStocks: ActiveStock[]
  researchRows?: ActiveResearchRow[]
  quality: DataSetQuality
}

export interface EventAnalysis {
  state: string
  items?: Array<{
    title: string
    source?: string
    publishedAt?: string
    url?: string
    verified?: boolean
  }>
  quality: DataSetQuality
}

export interface ChapterAssessment {
  state: string
  score?: number | null
  confidence: string
  evidence: string[]
  risks: string[]
  nextConfirmation?: string | null
  invalidation?: string | null
}

export interface CombinationOverview {
  strength: string
  stage: string
  capitalAcceptance: string
  tradingMode: string
  confidence: string
  evidence: string[]
}

export interface Chapter01Analysis {
  status: 'ok' | 'degraded' | 'insufficient' | string
  coverage: number
  documents?: ChapterDocument[]
  breadth?: BreadthAnalysis
  limits?: LimitAnalysis
  industryRanking?: ThsIndustryRanking
  sectorTurnover?: ThsSectorTurnover
  sectorBreadth?: ThsSectorBreadth
  sectorAnalysis?: SectorContinuityAnalysis
  activeDirection?: ActiveDirectionAnalysis
  activeDirectionWorkbench?: ActiveDirectionWorkbench
  events?: EventAnalysis
  combinationOverview: CombinationOverview
  marketEvidence?: MarketReviewEvidence | null
  reviewSentence?: ReviewSentence | null
  summarySentence?: string | null
  dataGaps?: DataGap[]
  assessment: ChapterAssessment
}

export interface ActiveDirectionWorkbench {
  asOf: string
  state: string
  quality: DataSetQuality & { missingInputs?: string[] }
  lineage?: Record<string, unknown>
  directionOverview?: Record<string, unknown>
  turnoverMap?: { rows: ActiveResearchRow[]; availableCount: number; complete: boolean }
  securityEvidence?: Record<string, Record<string, unknown>>
  candidatePools?: Record<string, unknown>
  fundamentals?: Record<string, unknown>
  validation?: Record<string, unknown> | null
}

export type ReviewSegmentStatus = 'available' | 'degraded' | 'insufficient' | 'unverified' | string

export interface MarketReviewEvidence {
  directionPattern?: string | null
  directionLabel?: string | null
  advancingIndexCount?: number | null
  decliningIndexCount?: number | null
  validIndexCount?: number | null
  aboveMa20Count?: number | null
  ma20ValidCount?: number | null
  medianAmountRatio5?: number | null
  volumeBackedAdvanceCount?: number | null
  volumeBackedDeclineCount?: number | null
  advanceRatio?: number | null
  medianReturn?: number | null
  status?: ReviewSegmentStatus
  warnings?: string[]
  dataGaps?: DataGap[]
}

export interface ReviewSentenceSegment {
  key: string
  label: string
  value: string
  status: ReviewSegmentStatus
  reason?: string | null
}

export interface ReviewSentence {
  status: ReviewSegmentStatus
  template: string
  segments: ReviewSentenceSegment[]
  fullSentence: string
  warnings?: string[]
}

export interface NextSessionComparison {
  status: 'available' | 'pending' | 'insufficient' | string
  requestedAsOf: string
  currentAsOf?: string | null
  nextAsOf?: string | null
  current?: MarketReviewEvidence | null
  next?: MarketReviewEvidence | null
  deltas: {
    directionPattern?: string | null
    advancingIndexCount?: number | null
    decliningIndexCount?: number | null
    aboveMa20Count?: number | null
    medianAmountRatio5?: number | null
    volumeBackedAdvanceCount?: number | null
    volumeBackedDeclineCount?: number | null
    advanceRatio?: number | null
    medianReturn?: number | null
  }
  warnings: string[]
}
