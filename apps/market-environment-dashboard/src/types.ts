export interface HistoryPoint {
  date: string
  close: number
  ma5: number | null
  ma10: number | null
  ma20: number | null
  ma60: number | null
  amount: number
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
  volumePriceState: string
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
}
