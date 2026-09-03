import type {
  CollectionRun,
  CollectionTaskStatus,
  DatasetCollectionStatus,
} from './collection-api'

export const STATUS_LABELS: Record<CollectionTaskStatus, string> = {
  queued: '等待采集',
  collecting: '采集中',
  success: '成功',
  partial: '部分成功',
  'failed-retained': '失败，保留旧值',
  'failed-missing': '失败，暂无数据',
  busy: '已有任务运行',
}

export function isRunActive(run: CollectionRun | null) {
  return run != null && ['queued', 'collecting'].includes(run.status)
}

export function statusTone(value: CollectionTaskStatus | undefined) {
  if (value === 'success') return 'success'
  if (value === 'partial' || value === 'failed-retained' || value === 'busy') return 'warning'
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
