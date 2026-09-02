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

export interface IndexAnalysis {
  code: string
  name: string
  representative: string
  changePct: number
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
  trendState: string
  volumePriceState: string | null
  combination: IndexCombination
  history: HistoryPoint[]
  dataQuality: {
    source: string
    isStale: boolean
    warning: string | null
  }
}

export interface MarketEnvironmentResponse {
  asOf: string
  generatedAt: string
  indices: IndexAnalysis[]
  summary: {
    synchronization: string
    dominantTrend: string
    warnings: string[]
  }
  chapter01?: Chapter01Analysis
}

export type Chapter01Section = 'breadth' | 'limits' | 'sectors' | 'activeDirection' | 'summary'

export interface Chapter01SectionResponse {
  asOf: string
  generatedAt: string
  chapter01: Chapter01Analysis
}

export interface DataSetQuality {
  dataset?: string
  source: string
  provider?: string
  status: 'ok' | 'fallback' | 'missing' | 'failed' | string
  warning?: string | null
  warnings?: string[]
  observations?: number
  asOf?: string
}

export interface ChapterDocument {
  id: string
  title: string
  document?: string
  status?: string
  ruleVersion?: string
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
}

export interface LimitAnalysis {
  limitUpCount: number | null
  limitDownCount: number | null
  failedLimitUpCount: number | null
  failedLimitUpRatio: number | null
  promotionRatio?: number | null
  maxStreak: number | null
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

export interface SectorAnalysis {
  state: string
  rows: SectorRow[]
  quality: DataSetQuality
}

export interface ActiveStock {
  code: string | null
  name: string | null
  changePct?: number | null
  amount?: number | null
  industry?: string | null
  closePosition?: number | null
}

export interface ActiveDirectionAnalysis {
  state: string
  summary?: string | null
  topStocks: ActiveStock[]
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
  tierRisk?: {
    state: string
    high?: number | null
    middle?: number | null
    low?: number | null
    repairRatio?: number | null
    quality: DataSetQuality
  }
  sectors?: SectorAnalysis
  activeDirection?: ActiveDirectionAnalysis
  events?: EventAnalysis
  combinationOverview: CombinationOverview
  assessment: ChapterAssessment
}
