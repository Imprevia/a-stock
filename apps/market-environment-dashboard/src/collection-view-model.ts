import type {
  CollectionRun,
  CollectionTaskStatus,
  DatasetCollectionStatus,
} from './collection-api'
import type { ThsDiagnostic } from './types'

export const STATUS_LABELS: Record<CollectionTaskStatus, string> = {
  queued: '等待采集',
  collecting: '采集中',
  success: '成功',
  partial: '部分成功',
  'failed-retained': '失败，保留旧值',
  'failed-missing': '失败，暂无数据',
  blocked: '依赖阻塞',
  busy: '已有任务运行',
}

export function isRunActive(run: CollectionRun | null) {
  return run != null && ['queued', 'collecting'].includes(run.status)
}

export function statusTone(value: CollectionTaskStatus | undefined) {
  if (value === 'success') return 'success'
  if (value === 'partial' || value === 'failed-retained' || value === 'blocked' || value === 'busy') return 'warning'
  if (value === 'collecting' || value === 'queued') return 'running'
  return 'failed'
}

export function availabilityLabel(item: DatasetCollectionStatus) {
  if (!item.available) return '暂无数据'
  return item.settled ? '可用 · 已结算' : '可用 · 暂定'
}

export function attemptLabel(item: DatasetCollectionStatus) {
  return item.latestAttempt ? STATUS_LABELS[item.latestAttempt.status] : '尚未采集'
}

function qualityDiagnostic(item: DatasetCollectionStatus): ThsDiagnostic | null {
  const value = item.quality?.diagnostics
  if (!value || typeof value !== 'object') return null
  return value as ThsDiagnostic
}

export function collectionDiagnostic(item: DatasetCollectionStatus): ThsDiagnostic | null {
  return item.latestAttempt?.diagnostics ?? qualityDiagnostic(item)
}

export function diagnosticCoverageLabel(
  item: DatasetCollectionStatus,
  diagnostic: ThsDiagnostic,
): string | null {
  const expected = diagnostic.expectedCount
  const usable = diagnostic.usableCount
    ?? (item.dataset === 'industry-ranking' ? diagnostic.rankableCount : null)
    ?? (item.dataset === 'sector-turnover' ? diagnostic.barCount : null)
    ?? diagnostic.observedCount
  if (expected == null || usable == null) return null
  return `可用 ${usable.toLocaleString('zh-CN')} / 预期 ${expected.toLocaleString('zh-CN')}`
}

export function diagnosticMissingLabel(diagnostic: ThsDiagnostic): string | null {
  const format = (label: string, totalValue: number | null | undefined, values: string[]) => {
    const samples = [...new Set(values)]
    const total = totalValue ?? samples.length
    if (!total && !samples.length) return null
    const sampleText = samples.length ? samples.join('、') : '未提供样例'
    const remaining = Math.max(0, total - samples.length)
    return `${label} ${total} 个：${sampleText}${remaining ? `（另 ${remaining} 个）` : ''}`
  }
  const parts = [
    format('当日行情缺失', diagnostic.missingLiveCount, diagnostic.missingLiveCodes ?? []),
    format('不可排名', diagnostic.missingRankingCount, diagnostic.missingRankingCodes ?? []),
  ].filter((value): value is string => Boolean(value))
  return parts.length ? parts.join('；') : null
}

export function diagnosticDependencyLabel(diagnostic: ThsDiagnostic): string | null {
  if (!diagnostic.blockedBy?.length) return null
  return `上游：${diagnostic.blockedBy.map((item) => (
    `${item.dataset}（${item.status}${item.reasonCode ? ` · ${item.reasonCode}` : ''}）`
  )).join('；')}`
}

export function collectionDiagnosticDetails(item: DatasetCollectionStatus): string[] {
  const diagnostic = collectionDiagnostic(item)
  if (!diagnostic) return []
  return [
    `原因 ${diagnostic.reasonCode}`,
    diagnosticCoverageLabel(item, diagnostic),
    diagnosticMissingLabel(diagnostic),
    diagnosticDependencyLabel(diagnostic),
    diagnostic.catalogRevisionId ? `目录版本 ${diagnostic.catalogRevisionId}` : null,
    `阶段 ${diagnostic.failureStage}`,
    diagnostic.retryable ? '可重试' : '不可直接重试',
  ].filter((value): value is string => Boolean(value))
}

export function canRetryDataset(
  manualRefreshEnabled: boolean,
  item: DatasetCollectionStatus,
  activeRun: CollectionRun | null,
) {
  return manualRefreshEnabled && item.collectionAllowed && !isRunActive(activeRun)
}

export function canCollectAll(
  manualRefreshEnabled: boolean,
  datasets: DatasetCollectionStatus[],
  activeRun: CollectionRun | null,
) {
  return manualRefreshEnabled
    && datasets.every((item) => item.collectionAllowed)
    && !isRunActive(activeRun)
}

export function toggleCoreExpansion(expanded: boolean) {
  return !expanded
}

export function getCollectionStatusRequestDate(selectedDate: string, dateInitialized: boolean) {
  return dateInitialized ? selectedDate : undefined
}

export function resolveCollectionSelectedDate(
  selectedDate: string,
  dateInitialized: boolean,
  serverDate: string,
) {
  return dateInitialized ? selectedDate : serverDate
}
