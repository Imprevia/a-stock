/**
 * useDocumentContext — read-only access to the cross-chapter derived
 * state and label dictionaries that the 9 document pages all need.
 *
 * Per spec `frontend-document-context`:
 * - exposes ONLY reactive computeds + pure helpers (no setXxx / loadXxx)
 * - chapters use this to read breadth/limits derivations and label maps
 * - any write action (loadCore, loadSection, setDate, ...) stays in
 *   `DashboardLayout` or `App.vue` via emit / provide
 */
import { computed, type ComputedRef } from 'vue'
import type { DataSetQuality, LimitStratificationRow } from '../types'
import { useMarketStore } from '../stores/market'

type QualityStatus = DataSetQuality['status']
type MetricStatus = 'ok' | 'insufficient' | 'degraded' | 'failed' | string
type SectionPhase = 'idle' | 'loading' | 'ready' | 'refreshing' | 'error'

export interface DocumentContext {
  // ── breadth derivations ─────────────────────────────────────────
  breadthHistoryRows: ComputedRef<NonNullable<NonNullable<ReturnType<typeof useMarketStore>['breadth']>['history']>['points']>
  breadthRuleRows: ComputedRef<Array<{
    id: string
    title: string
    valueLabel: string
    percentilePct: number
    percentileLabel: string
    scoreLabel: string
    weightLabel: string
  }>>
  breadthRuleSummary: ComputedRef<{ score: string; confidence: string; coverage: string; missing: string }>
  breadthIndexConsistencyRows: ComputedRef<Array<{
    code: string
    name: string
    changePct: number | null
    indexDirection: string
    medianDirection: string
    consistent: boolean | null
    hint: string
  }>>
  breadthConsistencySummary: ComputedRef<string>
  breadthVerification: ComputedRef<{ confirm: string; invalidate: string; consistencyHint: string }>
  breadthWarnings: ComputedRef<string[]>
  // ── limits derivations ──────────────────────────────────────────
  limitWarnings: ComputedRef<string[]>
  limitSectionPhase: ComputedRef<SectionPhase>
  promotionGap: ComputedRef<string>
limitHistory: ComputedRef<NonNullable<NonNullable<ReturnType<typeof useMarketStore>['limits']>['history']>['points']>
  limitHistoryMeta: ComputedRef<NonNullable<NonNullable<ReturnType<typeof useMarketStore>['limits']>>['history'] | null>
  limitTiers: ComputedRef<NonNullable<NonNullable<ReturnType<typeof useMarketStore>['limits']>['ladder']>>
  limitStratifications: ComputedRef<Array<{ label: string; rows: LimitStratificationRow[] }>>
  // ── label dictionaries (pure functions) ─────────────────────────
  qualityLabel: (quality?: DataSetQuality) => string
  qualityTone: (quality?: DataSetQuality) => 'ok' | 'fallback' | 'missing'
  metricQualityLabel: (status?: MetricStatus) => string
  metricQualityTone: (status?: MetricStatus) => 'ok' | 'fallback' | 'missing'
  qualityCodeLabel: (quality?: DataSetQuality) => string
  cacheStateLabel: (value?: string | null) => string
  sectionPhaseLabel: (phase: SectionPhase) => string
  confidenceLabel: (value?: string) => string
  assessmentStatusLabel: (value?: string) => string
  dimensionStatusLabel: (value?: string) => string
  reasonLabel: (value?: string | null) => string
  environmentLabel: (value?: string) => string
  gapLabel: (reason: string) => string
  formatRatioDelta: (value: number | null | undefined) => string
  formatReturnDelta: (value: number | null | undefined) => string
}

const QUALITY_LABEL: Record<string, string> = {
  ok: '正常',
  fallback: '降级来源',
  partial: '部分覆盖',
  missing: '缺失',
  failed: '失败',
  degraded: '降级保留',
  insufficient: '数据不足',
}

const QUALITY_TONE_OK: ReadonlyArray<QualityStatus> = ['ok']
const QUALITY_TONE_FALLBACK: ReadonlyArray<QualityStatus> = ['fallback', 'partial', 'degraded']

const METRIC_QUALITY_LABEL: Record<string, string> = {
  ok: '正常',
  insufficient: '数据不足',
  degraded: '降级',
  failed: '失败',
}

const SECTION_PHASE_LABEL: Record<SectionPhase, string> = {
  idle: '等待读取',
  loading: '正在读取',
  ready: '已就绪',
  refreshing: '正在刷新',
  error: '刷新失败',
}

const CONFIDENCE_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  insufficient: '数据不足',
}

const ASSESSMENT_STATUS_LABEL: Record<string, string> = {
  confirmed: '已确认',
  unconfirmed: '待确认',
  contradicted: '证据反驳',
  insufficient: '数据不足',
}

const DIMENSION_STATUS_LABEL: Record<string, string> = {
  confirming: '确认',
  neutral: '中性',
  contradicting: '反驳',
  insufficient: '不足',
}

const REASON_LABEL: Record<string, string> = {
  'current-breadth-unavailable': '当日市场广度不可用',
  'previous-breadth-unavailable': '精确上一交易日广度快照不可用',
  'fewer-than-three-ma20-observations': '有效 MA20 位置少于 3 个指数',
  'growth-turnover-unavailable': '创业板指与中证500成交额数据不完整',
  'fewer-than-three-turnover-observations': '有效成交额比值少于 3 个指数',
}

const ENVIRONMENT_LABEL: Record<string, string> = {
  trend: '趋势',
  rotation: '轮动',
  retreat: '退潮',
  mixed: '混合',
  insufficient: '数据不足',
}

const GAP_LABEL: Record<string, string> = {
  'insufficient-history': '历史窗口不足，暂无法计算分位',
  'missing-today': '当日行情尚未返回',
  'provider-failed': '行情供应商请求失败',
  'not-computable': '当前数据在数学上不可计算',
}

const STRATIFICATION_LABELS: Record<string, string> = {
  regime: '涨跌幅制度',
  board: '市场板块',
  exchange: '交易所',
  sector: '行业板块',
  risk_tier: '风险位阶',
  other: '其他分层',
}

function bandScore(percentile: number): string {
  if (percentile <= 0.2) return '0 分'
  if (percentile <= 0.4) return '25 分'
  if (percentile <= 0.6) return '50 分'
  if (percentile <= 0.8) return '75 分'
  return '100 分'
}

export function useDocumentContext(): DocumentContext {
  const market = useMarketStore()

  const breadthHistoryRows = computed(() => market.breadth?.history?.points ?? [])

  const breadthRuleRows = computed(() => {
    const item = market.breadth
    const percentilePct = (value: number | null | undefined): number =>
      value == null ? 0 : Math.round(value * 100)
    const percentileLabel = (value: number | null | undefined): string =>
      value == null ? '--' : `P${Math.round(value * 100)}`
    const scoreLabel = (value: number | null | undefined): string =>
      value == null ? '--' : bandScore(value)
    return [
      {
        id: 'QTS-01-02-01',
        title: '上涨占比',
        valueLabel: item?.advanceRatio == null ? '--' : formatPosition(item.advanceRatio),
        percentilePct: percentilePct(item?.advanceRatioPercentile),
        percentileLabel: percentileLabel(item?.advanceRatioPercentile),
        scoreLabel: scoreLabel(item?.advanceRatioPercentile),
        weightLabel: '30%',
      },
      {
        id: 'QTS-01-02-02',
        title: '涨跌差率',
        valueLabel: item?.advanceDeclineSpread == null
          ? '--'
          : `${item.advanceDeclineSpread > 0 ? '+' : ''}${(item.advanceDeclineSpread * 100).toFixed(0)}pp`,
        percentilePct: percentilePct(item?.spreadPercentile),
        percentileLabel: percentileLabel(item?.spreadPercentile),
        scoreLabel: scoreLabel(item?.spreadPercentile),
        weightLabel: '20%',
      },
      {
        id: 'QTS-01-02-03',
        title: '涨跌幅中位数',
        valueLabel: item?.medianReturn == null ? '--' : formatPct(item.medianReturn),
        percentilePct: percentilePct(item?.medianReturnPercentile),
        percentileLabel: percentileLabel(item?.medianReturnPercentile),
        scoreLabel: scoreLabel(item?.medianReturnPercentile),
        weightLabel: '30%',
      },
      {
        id: 'QTS-01-02-04',
        title: '5 日动量',
        valueLabel: item?.momentum == null
          ? '--'
          : `${item.momentum > 0 ? '+' : ''}${(item.momentum * 100).toFixed(1)}pp`,
        percentilePct: percentilePct(item?.momentumPercentile),
        percentileLabel: percentileLabel(item?.momentumPercentile),
        scoreLabel: scoreLabel(item?.momentumPercentile),
        weightLabel: '10%',
      },
      {
        id: 'QTS-01-02-05',
        title: '指数广度一致',
        valueLabel: item?.indexConsistent == null ? '--' : (item.indexConsistent ? '一致' : '背离'),
        percentilePct: item?.indexConsistent === true ? 100 : 0,
        percentileLabel: item?.indexConsistent == null ? '--' : (item.indexConsistent ? 'P100' : 'P0'),
        scoreLabel: item?.indexConsistent == null ? '--' : (item.indexConsistent ? '100 分' : '0 分'),
        weightLabel: '10%',
      },
    ]
  })

  const breadthRuleSummary = computed(() => {
    const item = market.breadth
    const scoreValues = [
      item?.advanceRatioPercentile,
      item?.spreadPercentile,
      item?.medianReturnPercentile,
      item?.momentumPercentile,
    ].filter((value): value is number => value != null)
    const indexScore = item?.indexConsistent === true ? 100 : item?.indexConsistent === false ? 0 : null
    const weights = [0.3, 0.2, 0.3, 0.1, 0.1]
    const available: Array<number | null> = [
      scoreValues[0] ?? null,
      scoreValues[1] ?? null,
      scoreValues[2] ?? null,
      scoreValues[3] ?? null,
      indexScore,
    ]
    const usable = available.filter((value): value is number => value != null)
    if (!usable.length) {
      return {
        score: '--',
        confidence: '数据不足',
        coverage: '0%',
        missing: '上涨占比 / 涨跌差率 / 中位数 / 5 日动量 / 指数一致全部缺失',
      }
    }
    const weighted = available.reduce((sum, value, index) => sum + (value ?? 0) * weights[index], 0)
      / available.reduce((sum, value, index) => sum + (value == null ? 0 : weights[index]), 0)
    const confidence = usable.length >= 5 ? '高' : usable.length >= 3 ? '中' : '低'
    const coverage = `${Math.round((usable.length / 5) * 100)}%`
    const missingList: string[] = []
    if (item?.advanceRatioPercentile == null) missingList.push('上涨占比分位')
    if (item?.spreadPercentile == null) missingList.push('涨跌差率分位')
    if (item?.medianReturnPercentile == null) missingList.push('中位数分位')
    if (item?.momentumPercentile == null) missingList.push('5 日动量分位')
    if (item?.indexConsistent == null) missingList.push('指数一致性')
    return {
      score: `${weighted.toFixed(1)} 分`,
      confidence,
      coverage,
      missing: missingList.length ? missingList.join('、') : '无',
    }
  })

  const breadthIndexConsistencyRows = computed(() => {
    const item = market.breadth
    const medianSign = item?.medianReturn == null ? null : Math.sign(item.medianReturn)
    const medianDirection = medianSign == null ? '--' : medianSign > 0 ? '↑' : medianSign < 0 ? '↓' : '→'
    return (market.data?.indices ?? []).map((index) => {
      const change = index.changePct
      const changeSign = change == null ? null : Math.sign(change)
      const indexDirection = changeSign == null ? '--' : changeSign > 0 ? '↑' : changeSign < 0 ? '↓' : '→'
      const consistent = changeSign != null && medianSign != null ? changeSign === medianSign : null
      const hint = consistent == null
        ? `${index.name}涨跌缺失`
        : consistent
          ? `${index.name}同步${indexDirection === '↑' ? '偏强' : '偏弱'}`
          : `${index.name}与广度${indexDirection === '↑' ? '强' : '弱'}背离`
      return {
        code: index.code,
        name: index.name,
        changePct: change,
        indexDirection,
        medianDirection,
        consistent,
        hint,
      }
    })
  })

  const breadthConsistencySummary = computed(() => {
    const rows = breadthIndexConsistencyRows.value.filter((row) => row.consistent != null)
    if (!rows.length) return '数据不足'
    const same = rows.filter((row) => row.consistent).length
    if (same === rows.length) return `${same} / ${rows.length} 强一致`
    if (same >= rows.length - 1) return `${same} / ${rows.length} 多数一致`
    return `${same} / ${rows.length} 权重分歧`
  })

  const breadthVerification = computed(() => {
    const item = market.breadth
    if (!item?.advanceRatio || item.medianReturn == null) {
      return { confirm: '数据不足，等待新增证据', invalidate: '数据不足，等待新增证据', consistencyHint: '缺失' }
    }
    const sameDirection = (item.indexConsistent ?? false) ? '一致' : '背离'
    const medianFloor = item.advanceRatio >= 0.6 ? '+0.50%' : '+0.30%'
    return {
      confirm: `上涨占比 ≥ 60% 且中位数 ≥ ${medianFloor}`,
      invalidate: '上涨占比 < 40% 或中位数 < -0.30%',
      consistencyHint: sameDirection,
    }
  })

  const breadthWarnings = computed(() => {
    const item = market.breadth
    const warnings = [item?.quality?.warning, ...(item?.quality?.warnings ?? [])]
    return [...new Set(warnings.filter((warning): warning is string => Boolean(warning)))]
  })

  const limitWarnings = computed(() => {
    const item = market.limits
    const warnings = [item?.quality.warning, ...(item?.quality.warnings ?? []), item?.quality.refreshWarning]
    if (item?.promotionQuality) warnings.push(...(item.promotionQuality.warnings ?? []))
    for (const quality of Object.values(item?.fieldQuality ?? {})) warnings.push(...(quality?.warnings ?? []))
    return [...new Set(warnings.filter((warning): warning is string => Boolean(warning)))]
  })

  const limitSectionPhase = computed<SectionPhase>(() => {
    const phase = market.sectionStates.limits.phase
    if (phase === 'ready' && market.limits?.quality.refreshing) return 'refreshing'
    return phase
  })

  const promotionGap = computed(() => {
    if (market.limits?.promotionRatio != null) return ''
    const reason = market.limits?.promotionQuality?.reason
    return ({
      'zero-denominator': '昨日合格样本为 0，晋级率没有可计算分母。',
      'missing-limits-dataset': '所选交易日缺少涨跌停数据集。',
      'incomplete-pool-input': '涨跌停池输入不完整，无法形成晋级样本。',
      'promotion-calculation-failed': '晋级证据计算失败，未返回比例。',
      'missing-previous-session': '缺少精确前一交易日样本，无法完成跨日匹配。',
    } as Record<string, string>)[reason ?? ''] ?? '缺少昨日合格收盘涨停样本、逐证券跨日匹配或收盘涨停验证。'
  })

  const limitHistory = computed(() => market.limits?.history?.points ?? market.limits?.historical?.points ?? [])
  const limitHistoryMeta = computed(() => market.limits?.history ?? market.limits?.historical ?? null)
  const limitTiers = computed(() => market.limits?.ladder ?? market.limits?.tiers ?? [])

  const limitStratifications = computed(() => {
    const groups = new Map<string, { label: string; rows: LimitStratificationRow[] }>()
    for (const row of market.limits?.stratifications ?? []) {
      const key = String((row as { dimension?: string }).dimension ?? 'other')
      const group = groups.get(key) ?? { label: STRATIFICATION_LABELS[key] ?? STRATIFICATION_LABELS.other, rows: [] }
      group.rows.push(row)
      groups.set(key, group)
    }
    return [...groups.values()]
  })

  function qualityLabel(quality?: DataSetQuality): string {
    return quality ? (QUALITY_LABEL[quality.status] ?? quality.status) : '数据不足'
  }
  function qualityTone(quality?: DataSetQuality): 'ok' | 'fallback' | 'missing' {
    if (!quality) return 'missing'
    if (QUALITY_TONE_OK.includes(quality.status)) return 'ok'
    if (QUALITY_TONE_FALLBACK.includes(quality.status)) return 'fallback'
    return 'missing'
  }
  function metricQualityLabel(status?: MetricStatus): string {
    return METRIC_QUALITY_LABEL[status ?? ''] ?? status ?? '数据不足'
  }
  function metricQualityTone(status?: MetricStatus): 'ok' | 'fallback' | 'missing' {
    if (status === 'ok') return 'ok'
    if (status === 'degraded') return 'fallback'
    return 'missing'
  }
  function qualityCodeLabel(quality?: DataSetQuality): string {
    return `${quality?.status ?? 'missing'} · ${qualityLabel(quality)}`
  }
  function cacheStateLabel(value?: string | null): string {
    return ({ fresh: '新鲜', stale: '陈旧', missing: '缺失' } as Record<string, string>)[value ?? ''] ?? '未提供'
  }
  function sectionPhaseLabel(phase: SectionPhase): string {
    return SECTION_PHASE_LABEL[phase]
  }
  function confidenceLabel(value?: string): string {
    return CONFIDENCE_LABEL[value ?? ''] ?? value ?? '数据不足'
  }
  function assessmentStatusLabel(value?: string): string {
    return ASSESSMENT_STATUS_LABEL[value ?? ''] ?? value ?? '数据不足'
  }
  function dimensionStatusLabel(value?: string): string {
    return DIMENSION_STATUS_LABEL[value ?? ''] ?? value ?? '不足'
  }
  function reasonLabel(value?: string | null): string {
    return REASON_LABEL[value ?? ''] ?? value ?? ''
  }
  function environmentLabel(value?: string): string {
    return ENVIRONMENT_LABEL[value ?? ''] ?? value ?? '数据不足'
  }
  function gapLabel(reason: string): string {
    return GAP_LABEL[reason] ?? '数据不足'
  }
  function formatRatioDelta(value: number | null | undefined): string {
    return value == null ? '--' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} 个百分点`
  }
  function formatReturnDelta(value: number | null | undefined): string {
    return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)} 个百分点`
  }
  function formatPosition(value: number | null | undefined): string {
    return value == null ? '--' : `${(value * 100).toFixed(0)}%`
  }
  function formatPct(value: number | null | undefined): string {
    return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
  }

  return {
    breadthHistoryRows,
    breadthRuleRows,
    breadthRuleSummary,
    breadthIndexConsistencyRows,
    breadthConsistencySummary,
    breadthVerification,
    breadthWarnings,
    limitWarnings,
    limitSectionPhase,
    promotionGap,
    limitHistory,
    limitHistoryMeta,
    limitTiers,
    limitStratifications,
    qualityLabel,
    qualityTone,
    metricQualityLabel,
    metricQualityTone,
    qualityCodeLabel,
    cacheStateLabel,
    sectionPhaseLabel,
    confidenceLabel,
    assessmentStatusLabel,
    dimensionStatusLabel,
    reasonLabel,
    environmentLabel,
    gapLabel,
    formatRatioDelta,
    formatReturnDelta,
  }
  void formatPosition
  void formatPct
}