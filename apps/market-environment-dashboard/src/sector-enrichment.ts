import type { SectorEnrichmentQuality } from './types'

const FIELD_LABELS: Record<string, string> = {
  f62: '主力净额',
  f104: '上涨家数',
  f105: '下跌家数',
  f128: '领涨股',
  f184: '主力净额比例',
  mainNet: '主力净额',
  mainNetPct: '主力净额比例',
  upCount: '上涨家数',
  downCount: '下跌家数',
  leader: '领涨股',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function sectorEnrichmentFromQuality(quality: unknown): SectorEnrichmentQuality | null {
  if (!isRecord(quality) || !isRecord(quality.sectorEnrichment)) return null
  return quality.sectorEnrichment as SectorEnrichmentQuality
}

export function sectorEnrichmentStatusLabel(status?: string | null): string {
  switch (status) {
    case 'enriched':
    case 'complete':
    case 'ok':
      return '已补充'
    case 'partial':
      return '部分补充'
    case 'base-only':
    case 'base_only':
    case 'skipped':
      return '仅基础结果'
    case 'disabled':
      return '未启用'
    case 'failed':
      return '补充失败'
    default:
      return status ? status : '字段补充'
  }
}

export function sectorEnrichmentSourceLabel(enrichment?: SectorEnrichmentQuality | null): string {
  if (!enrichment) return ''
  const source = enrichment.source || '东方财富 dataapi'
  const displaySource = /eastmoney|dataapi/i.test(source) ? '东方财富 dataapi' : source
  return `同供应商字段补充：${displaySource}`
}

export function formatCoverage(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (value >= 0 && value <= 1) return `${(value * 100).toFixed(0)}%`
  return `${value.toFixed(0)}%`
}

function formatFieldCoverage(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (value >= 0 && value <= 1) return `${(value * 100).toFixed(0)}%`
  return `${value.toLocaleString('zh-CN')} 行`
}

export function sectorEnrichmentCoverage(enrichment?: SectorEnrichmentQuality | null): string[] {
  if (!enrichment) return []
  const details: string[] = []
  if (enrichment.identityCoverage != null) {
    const coverage = formatCoverage(enrichment.identityCoverage)
    if (coverage) details.push(`身份匹配 ${coverage}`)
  }
  if (enrichment.matchedRows != null || enrichment.unmatchedRows != null) {
    details.push(`匹配 ${enrichment.matchedRows ?? '--'} 行 · 未匹配 ${enrichment.unmatchedRows ?? '--'} 行`)
  }
  if (isRecord(enrichment.fieldCoverage)) {
    const fields = Object.entries(enrichment.fieldCoverage)
      .map(([key, raw]) => {
        const label = FIELD_LABELS[key] || key
        if (isRecord(raw)) {
          const coverage = formatCoverage(raw.coverage)
          if (coverage) return `${label} ${coverage}`
          if (typeof raw.matched === 'number' || typeof raw.total === 'number') {
            return `${label} ${raw.matched ?? '--'}/${raw.total ?? '--'}`
          }
          return null
        }
        const coverage = formatFieldCoverage(raw)
        return coverage ? `${label} ${coverage}` : null
      })
      .filter((value): value is string => Boolean(value))
    if (fields.length) details.push(`字段覆盖：${fields.join('、')}`)
  }
  return details
}

export function sectorEnrichmentDateLabel(enrichment?: SectorEnrichmentQuality | null): string | null {
  if (!enrichment?.dateEvidence) return null
  if (typeof enrichment.dateEvidence === 'string') return enrichment.dateEvidence
  const evidence = enrichment.dateEvidence
  const reason = evidence.reason || evidence.evidence || evidence.status
  if (typeof reason === 'string') return reason
  const requested = evidence.requested || evidence.asOf || evidence.currentAsOf
  return typeof requested === 'string' ? `仅当前日期：${requested}` : '仅允许当前上海交易日补充'
}

export function sectorEnrichmentWarnings(enrichment?: SectorEnrichmentQuality | null): string[] {
  const warnings = enrichment?.warnings
  return Array.isArray(warnings)
    ? warnings.filter((warning): warning is string => typeof warning === 'string' && warning.length > 0)
    : []
}
