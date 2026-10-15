import type { ThsDiagnostic, ThsSectorBar, ThsSectorTag } from './types'

export const COLLECTION_DATASETS = [
  'core',
  'breadth',
  'limits',
  'industry-ranking',
  'sector-turnover',
  'sector-breadth',
  'activeDirection',
] as const

export type CollectionDataset = typeof COLLECTION_DATASETS[number]
export type CollectionRunStatus = 'queued' | 'collecting' | 'success' | 'partial' | 'failed'
export type CollectionTaskStatus = 'queued' | 'collecting' | 'success' | 'partial' | 'failed-retained' | 'failed-missing' | 'blocked' | 'busy'
export type CollectionFailureCategory =
  | 'configuration'
  | 'engine-unavailable'
  | 'network'
  | 'rate-limit'
  | 'permission'
  | 'challenge'
  | 'contract'
  | 'date-mismatch'
  | 'insufficient'
  | 'internal'
  | 'dependency'
  | 'concurrency'
  | 'worker-interrupted'

export const LEGACY_SECTORS_MIGRATION_MESSAGE = '数据集 sectors 已停止支持；请改用 industry-ranking、sector-turnover 或 sector-breadth。'

export function isCollectionDataset(value: string): value is CollectionDataset {
  return (COLLECTION_DATASETS as readonly string[]).includes(value)
}

export interface CoreIndexCollectionResult {
  code: string
  name: string
  status: CollectionTaskStatus
  source: string
  observations: number
  warning: string | null
  durationMs: number | null
}

export interface CollectionTaskFailure {
  category: CollectionFailureCategory
  message: string
  retryable: boolean
  retained: boolean
  source?: string | null
  stage?: string | null
  code?: string | null
  blockedBy?: string[]
}

export interface CollectionAttempt {
  taskId: string
  runId: string
  status: CollectionTaskStatus
  source: string
  observations: number
  warning: string | null
  failure?: CollectionTaskFailure | null
  diagnostics?: ThsDiagnostic | null
  catalogRevisionId?: string | null
  queuedAt: string | null
  startedAt: string | null
  completedAt: string | null
  durationMs: number | null
  settled: boolean
  sampleAsOf?: string | null
  previousAsOf?: string | null
  excludedCount?: number | null
  promotionQuality?: string | null
  promotionDependency?: string | null
  promotionRequired?: boolean | null
  quality?: Record<string, unknown> | null
}

export interface LimitsCollectionDetail {
  sampleAsOf?: string | null
  previousAsOf?: string | null
  excludedCount?: number | null
  promotionQuality?: string | null
  promotionDependency?: string | null
  promotionRequired?: boolean | null
  warnings?: string[]
}

export interface DatasetCollectionStatus {
  dataset: CollectionDataset
  available: boolean
  source: string
  observations: number
  lastSuccessAt: string | null
  settled: boolean
  refreshWarning: string | null
  quality?: Record<string, unknown> | null
  catalogRevisionId?: string | null
  latestAttempt: CollectionAttempt | null
  activeTaskId: string | null
  collectionAllowed: boolean
  restriction: string | null
  coreIndices: CoreIndexCollectionResult[]
  detail?: LimitsCollectionDetail | null
}

export interface SectorAnalysisReadinessVersions {
  data?: string | null
  classification?: string | null
  membership?: string | null
  universe?: string | null
  adjustment?: string | null
  benchmark?: string | null
  calculation?: string | null
}

export interface SectorAnalysisBackfillProgress {
  runId?: string | null
  status?: string | null
  completedSessions?: number | null
  totalSessions?: number | null
  failedSessions?: number | null
  startedAt?: string | null
  completedAt?: string | null
}

export interface SectorAnalysisReadinessAttempt {
  runId?: string | null
  status: string
  retryEligible: boolean
  warning?: string | null
  completedAt?: string | null
}

export interface SectorAnalysisReadiness {
  asOf: string
  status: string
  requiredHistory: number
  availableHistory: number
  missingSessions: string[]
  coverage: number | null
  versions?: SectorAnalysisReadinessVersions | null
  latestAttempt?: SectorAnalysisReadinessAttempt | null
  backfill?: SectorAnalysisBackfillProgress | null
  warnings: string[]
  retryEligible: boolean
}

export interface CollectionStatusResponse {
  asOf: string
  manualRefreshEnabled: boolean
  datasets: DatasetCollectionStatus[]
  sectorAnalysis?: SectorAnalysisReadiness | null
  operations?: ThsOperationProgress[]
}

export interface CollectionTask extends Omit<CollectionAttempt, 'runId'> {
  dataset: CollectionDataset
  asOf: string
  timings: Record<string, number>
  coreIndices: CoreIndexCollectionResult[]
}

export interface CollectionRun {
  runId: string
  asOf: string
  status: CollectionRunStatus
  requestedDatasets: CollectionDataset[]
  completedTasks: number
  totalTasks: number
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  tasks: CollectionTask[]
}

export interface ThsCatalogRevision {
  catalogRevisionId: string
  revisionId?: string
  capabilityRevision: string
  providerTimestamp: string
  fetchedAt: string
  tagCounts: Record<ThsSectorTag, number>
  checksum: string
}

export interface ThsCatalogItem {
  tag: ThsSectorTag
  thscode: string
  name: string
}

export interface ThsCatalogResponse {
  revision: ThsCatalogRevision | null
  items: ThsCatalogItem[]
  page: number
  pageSize: number
  total: number
}

export interface ThsBarCoverage {
  firstDate: string | null
  lastDate: string | null
  storedRows: number
  gaps: string[]
}

export interface ThsSectorBarsResponse {
  thscode: string
  requestedStart: string | null
  requestedEnd: string | null
  coverage: ThsBarCoverage
  items: ThsSectorBar[]
  page: number
  pageSize: number
  total: number
}

export interface ThsOperationCheckpoint {
  thscode?: string | null
  windowStart?: string | null
  windowEnd?: string | null
  status: string
  rowsWritten?: number | null
  rowsSkipped?: number | null
  conflicts?: number | null
  warning?: string | null
}

export interface ThsOperationProgress {
  runId: string
  kind: string
  status: string
  progress: {
    completed: number
    total: number
    failed: number
    conflicts: number
  }
  warning: string | null
  checkpoints: ThsOperationCheckpoint[]
}

export interface QueuedThsOperation {
  runId: string
  status: 'queued' | string
}

export interface ThsCatalogQuery {
  tag?: ThsSectorTag
  search?: string
  revision?: string
  page?: number
  pageSize?: number
}

export interface ThsCatalogSyncRequest {
  asOf?: string
  membershipThscodes?: string[]
  requestBudget?: number
}

export interface ThsSectorBarsQuery {
  startDate?: string
  endDate?: string
  page?: number
  pageSize?: number
}

export interface ThsTurnoverBackfillRequest {
  thscodes: string[]
  startDate: string
  endDate: string
  requestBudget?: number
}

export interface ThsMemberFactsImportRequest {
  asOf: string
  sourceRevision: string
  requestBudget?: number
  daily: ThsDumpFileRequest
  adjustment: ThsDumpFileRequest
  incremental?: ThsDumpFileRequest
}

export interface ThsDumpFileRequest {
  path: string
  dumpId: string
  schemaRevision: string
  capabilityRevision: string
  checksum: string
  startDate: string
  endDate: string
}

export async function fetchCollectionStatus(asOf?: string): Promise<CollectionStatusResponse> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
  return requestJson(`/api/market-environment/data-collection${query}`)
}

export async function startCollectionRun(
  asOf: string,
  datasets?: CollectionDataset[],
): Promise<CollectionRun> {
  if (datasets?.some((dataset) => !isCollectionDataset(dataset))) {
    throw new Error(LEGACY_SECTORS_MIGRATION_MESSAGE)
  }
  return requestJson('/api/market-environment/collection-runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asOf, ...(datasets ? { datasets } : {}) }),
  })
}

export async function fetchCollectionRun(runId: string): Promise<CollectionRun> {
  return requestJson(`/api/market-environment/collection-runs/${encodeURIComponent(runId)}`)
}

export async function pollCollectionRun(
  runId: string,
  options: { intervalMs?: number; isCurrent?: () => boolean } = {},
): Promise<CollectionRun | null> {
  const intervalMs = options.intervalMs ?? 600
  while (options.isCurrent?.() !== false) {
    const run = await fetchCollectionRun(runId)
    if (options.isCurrent?.() === false) return null
    if (!['queued', 'collecting'].includes(run.status)) return run
    await new Promise((resolve) => globalThis.setTimeout(resolve, intervalMs))
  }
  return null
}

export async function fetchThsCatalog(query: ThsCatalogQuery = {}): Promise<ThsCatalogResponse> {
  const params = new URLSearchParams()
  if (query.tag) params.set('tag', query.tag)
  if (query.search) params.set('search', query.search)
  if (query.revision) params.set('revision', query.revision)
  if (query.page != null) params.set('page', String(query.page))
  if (query.pageSize != null) params.set('page_size', String(query.pageSize))
  const suffix = params.size ? `?${params.toString()}` : ''
  const response = await requestJson<ThsCatalogResponse>(
    `/api/market-environment/ths/catalog${suffix}`,
  )
  const revision = response.revision as Partial<ThsCatalogRevision> | null
  if (revision && !revision.catalogRevisionId && revision.revisionId) {
    revision.catalogRevisionId = revision.revisionId
  }
  return response
}

export async function fetchThsSectorBars(
  thscode: string,
  query: ThsSectorBarsQuery = {},
): Promise<ThsSectorBarsResponse> {
  const params = new URLSearchParams()
  if (query.startDate) params.set('start_date', query.startDate)
  if (query.endDate) params.set('end_date', query.endDate)
  if (query.page != null) params.set('page', String(query.page))
  if (query.pageSize != null) params.set('page_size', String(query.pageSize))
  const suffix = params.size ? `?${params.toString()}` : ''
  return requestJson(`/api/market-environment/ths/sectors/${encodeURIComponent(thscode)}/bars${suffix}`)
}

export async function fetchThsOperation(runId: string): Promise<ThsOperationProgress> {
  return requestJson(`/api/market-environment/ths/operations/${encodeURIComponent(runId)}`)
}

export async function pollThsOperation(
  runId: string,
  options: { intervalMs?: number; isCurrent?: () => boolean } = {},
): Promise<ThsOperationProgress | null> {
  const intervalMs = options.intervalMs ?? 600
  while (options.isCurrent?.() !== false) {
    const operation = await fetchThsOperation(runId)
    if (options.isCurrent?.() === false) return null
    if (!['queued', 'running'].includes(operation.status)) return operation
    await new Promise((resolve) => globalThis.setTimeout(resolve, intervalMs))
  }
  return null
}

export async function startThsCatalogSync(
  request: ThsCatalogSyncRequest = {},
): Promise<QueuedThsOperation> {
  return requestJson('/api/market-environment/ths/catalog/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function startSectorTurnoverBackfill(
  request: ThsTurnoverBackfillRequest,
): Promise<QueuedThsOperation> {
  return requestJson('/api/market-environment/ths/turnover/backfills', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function startThsMemberFactsImport(
  request: ThsMemberFactsImportRequest,
): Promise<QueuedThsOperation> {
  return requestJson('/api/market-environment/ths/member-facts/imports', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}
